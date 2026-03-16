"""LangChain Attraction sub-agent for recommendations and attraction details."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from serpapi import GoogleSearch

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from attraction_tool import (  # noqa: E402
    clean_opening_hours,
    get_attraction_info,
    get_attractions_by_place,
    is_valid_opening_hours,
)


@tool
def attraction_recommendation_tool(city: str, query_hint: str = "") -> dict[str, Any]:
    """Return attraction candidates by city."""
    attractions = get_attractions_by_place(place=city, query_type=query_hint or None)
    return {
        "city": city,
        "attractions": attractions,
        "sources": [
            item.get("source_link", "")
            for item in attractions
            if isinstance(item, dict) and item.get("source_link")
        ],
    }


def _normalize_city(text: str) -> str:
    query = str(text or "").strip()
    if not query:
        return ""

    patterns = [
        r"top attractions in\s+([A-Za-z\s\-]+)",
        r"attractions in\s+([A-Za-z\s\-]+)",
        r"([A-Za-z\s\-]+)\s+attractions",
        r"([\u4e00-\u9fffA-Za-z\s\-]+?)\s*(?:有什么好玩的景点|有什么值得去的景点|景点推荐|推荐景点)",
    ]

    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,!，。")

    cleaned = re.sub(r"(有什么好玩的景点|有什么值得去的景点|景点推荐|推荐景点|attractions?)", "", query, flags=re.IGNORECASE)
    return cleaned.strip(" .,!，。")


def _is_recommendation_query(query: str) -> bool:
    text = str(query or "").lower()
    recommendation_tokens = [
        "有什么好玩的景点",
        "有什么值得去的景点",
        "景点推荐",
        "推荐景点",
        "top attractions",
        "things to do",
        "attractions in",
        "attractions",
    ]
    if any(token in text for token in recommendation_tokens):
        return True
    return any(token in query for token in ["景点", "好玩", "值得去"])


def _clean_ticket_price(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    blocked = ["estimated", "unknown", "official price not found", "none", "null"]
    if any(token in lowered for token in blocked):
        return ""

    if not re.search(r"\bRM\b", text):
        return ""
    return text


def _compact_description(text: Any) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    content = re.sub(r"\s+", " ", content)
    return content[:180].rstrip()


def _normalize_opening_hours(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    cleaned = clean_opening_hours(raw)
    if cleaned and is_valid_opening_hours(cleaned):
        return cleaned
    return ""


def _search_city_candidates(city: str, api_key: str, limit: int = 8) -> list[dict[str, str]]:
    if not city or not api_key:
        return []

    params = {
        "engine": "google",
        "q": f"top attractions in {city}",
        "hl": "en",
        "num": max(limit, 8),
        "api_key": api_key,
    }
    try:
        payload = GoogleSearch(params).get_dict()
    except Exception:
        return []

    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload.get("organic_results", [])[:12]:
        title = str(item.get("title", "")).strip()
        link = str(item.get("link", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        if not title:
            continue

        name = re.split(r"\s[-|–:]\s", title)[0].strip()
        if len(name) < 3:
            continue
        lowered = name.lower()
        if any(bad in lowered for bad in ["things to do", "best attractions", "tripadvisor", "wikipedia"]):
            continue
        if lowered in seen:
            continue
        seen.add(lowered)

        candidates.append({"name": name, "brief_description": snippet, "source_link": link})
        if len(candidates) >= limit:
            break
    return candidates


def _build_recommendation_from_city(city: str, query: str) -> dict[str, Any]:
    candidates = get_attractions_by_place(place=city, query_type=query)
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if len(candidates) < 3:
        fallback = _search_city_candidates(city=city, api_key=api_key, limit=10)
        existing = {str(item.get("name", "")).strip().lower() for item in candidates if isinstance(item, dict)}
        for item in fallback:
            key = item.get("name", "").strip().lower()
            if key and key not in existing:
                candidates.append(item)
                existing.add(key)

    attractions: list[dict[str, str]] = []
    sources: list[str] = []
    seen_names: set[str] = set()

    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        key = name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)

        detail = get_attraction_info(attraction_name=name, location=city)
        detail_sources = detail.get("sources", []) if isinstance(detail, dict) else []
        if isinstance(detail_sources, list):
            for src in detail_sources:
                url = str(src or "").strip()
                if url:
                    sources.append(url)

        description = _compact_description(detail.get("description")) or _compact_description(item.get("brief_description"))
        image = str(detail.get("image_url") or detail.get("image") or "").strip()
        ticket_price = _clean_ticket_price(detail.get("ticket_price"))

        enriched = {
            "name": name,
            "description": description,
            "image": image,
            "ticket_price": ticket_price,
        }
        attractions.append(enriched)
        if len(attractions) >= 6:
            break

    if not attractions and city:
        attractions.append(
            {
                "name": city,
                "description": f"Popular attractions in {city}.",
                "image": "",
                "ticket_price": "",
            }
        )

    deduped_sources: list[str] = []
    seen_source: set[str] = set()
    for src in sources:
        if src in seen_source:
            continue
        seen_source.add(src)
        deduped_sources.append(src)

    return {
        "query_type": "attraction_recommendation",
        "city": city,
        "attractions": attractions,
        "sources": deduped_sources[:10],
    }


@tool
def attraction_detail_tool(attraction_name: str, location: str = "") -> dict[str, Any]:
    """Return attraction details by attraction name and optional location."""
    return get_attraction_info(attraction_name=attraction_name, location=location or None)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from model text."""
    text = (text or "").strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}

    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("output_text") or ""
                if text:
                    chunks.append(str(text))
        return "\n".join(chunks).strip()

    if isinstance(content, dict):
        text = content.get("text") or content.get("output_text") or ""
        if text:
            return str(text).strip()

    return str(content or "").strip()


def _extract_payload_from_output(output: Any) -> dict[str, Any]:
    text = _content_to_text(output)
    if not text:
        return {}

    # Support fenced JSON like ```json {...}``` from model output.
    if "```" in text:
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    payload = _extract_json_object(text)
    if payload:
        return payload

    # If plain text parse fails, try extracting from serialized object content.
    return _extract_json_object(json.dumps(output, ensure_ascii=False))


def _normalize_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    city = str(payload.get("city", "")).strip()

    raw_attractions = payload.get("attractions", [])
    if not isinstance(raw_attractions, list):
        raw_attractions = []

    normalized_attractions: list[dict[str, str]] = []
    for item in raw_attractions:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            description = _compact_description(item.get("description"))
            image = str(item.get("image") or item.get("image_url") or "").strip()
            ticket_price = _clean_ticket_price(item.get("ticket_price"))
        else:
            name = str(item).strip()
            description = ""
            image = ""
            ticket_price = ""
        if name:
            normalized_attractions.append(
                {
                    "name": name,
                    "description": description,
                    "image": image,
                    "ticket_price": ticket_price,
                }
            )

    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = []
    sources = [str(src).strip() for src in raw_sources if str(src).strip()]

    return {
        "query_type": "attraction_recommendation",
        "city": city,
        "attractions": normalized_attractions,
        "sources": sources,
    }


def _normalize_info(payload: dict[str, Any]) -> dict[str, Any]:
    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = []

    sources: list[str] = []
    for src in raw_sources:
        if isinstance(src, dict):
            link = str(src.get("link", "")).strip()
            if link:
                sources.append(link)
        else:
            text = str(src).strip()
            if text:
                sources.append(text)

    description = _compact_description(payload.get("description"))
    image = str(payload.get("image") or payload.get("image_url") or "").strip()
    opening_hours = _normalize_opening_hours(payload.get("opening_hours"))
    visit_duration = str(payload.get("visit_duration") or "").strip()
    ticket_price = _clean_ticket_price(payload.get("ticket_price"))

    return {
        "query_type": "attraction_info",
        "name": str(payload.get("name", "")).strip(),
        "description": description,
        "image": image,
        "opening_hours": opening_hours,
        "visit_duration": visit_duration,
        "ticket_price": ticket_price,
        "sources": sources,
    }


def _is_placeholder_api_key(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return True

    upper_value = normalized.upper()
    return upper_value.startswith("YOUR_") or "PLACEHOLDER" in upper_value


def _resolve_google_api_key() -> str:
    load_dotenv()

    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()

    gemini_valid = not _is_placeholder_api_key(gemini_api_key)
    google_valid = not _is_placeholder_api_key(google_api_key)

    if gemini_valid:
        resolved_key = gemini_api_key
    elif google_valid:
        resolved_key = google_api_key
    else:
        raise ValueError(
            "Missing a valid Google/Gemini API key. Set GEMINI_API_KEY or GOOGLE_API_KEY "
            "in your environment or .env, and replace placeholder values like "
            "'YOUR_GOOGLE_API_KEY'."
        )

    # The Google client prefers GOOGLE_API_KEY when both are present, so keep them aligned.
    os.environ["GEMINI_API_KEY"] = resolved_key
    os.environ["GOOGLE_API_KEY"] = resolved_key
    return resolved_key


def _build_executor() -> Any:
    api_key = _resolve_google_api_key()

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        api_key=api_key,
        temperature=0,
    )

    tools = [attraction_recommendation_tool, attraction_detail_tool]
    system_prompt = (
        "You are the Attraction sub-agent. Classify each query into one of two tasks and use tools.\n"
        "1) attraction_recommendation: recommend attractions for a city.\n"
        "2) attraction_info: fetch details for one attraction.\n"
        "Output must be a strict JSON object only, with no markdown and no extra commentary.\n"
        "Recommendation JSON schema:\n"
        "{\"query_type\":\"attraction_recommendation\",\"city\":\"string\",\"attractions\":[{\"name\":\"string\"}],\"sources\":[]}\n"
        "Info JSON schema:\n"
        "{\"query_type\":\"attraction_info\",\"name\":\"string\",\"opening_hours\":\"string\",\"visit_duration\":\"string\",\"ticket_price\":\"string\",\"sources\":[]}\n"
        "Use tools whenever possible and keep all fields present."
    )
    return create_agent(model=llm, tools=tools, system_prompt=system_prompt)


def run_attraction_agent(query: str) -> dict[str, Any]:
    """Attraction sub-agent entrypoint."""
    if _is_recommendation_query(query):
        city = _normalize_city(query)
        if city:
            return _build_recommendation_from_city(city=city, query=query)

    executor = _build_executor()
    result = executor.invoke({"messages": [("user", query)]})
    messages = result.get("messages", []) if isinstance(result, dict) else []
    output = messages[-1].content if messages else ""
    payload = _extract_payload_from_output(output)

    query_type = str(payload.get("query_type", "")).strip()
    if query_type == "attraction_recommendation":
        city = _normalize_city(payload.get("city") or query)
        normalized = _normalize_recommendation(payload)
        if normalized.get("attractions"):
            return normalized
        if city:
            return _build_recommendation_from_city(city=city, query=query)
        return normalized
    if query_type == "attraction_info":
        normalized_info = _normalize_info(payload)
        if normalized_info.get("name"):
            return normalized_info
        detail = get_attraction_info(attraction_name=query, location=None)
        return _normalize_info(detail)

    if "attractions" in payload or "city" in payload:
        normalized = _normalize_recommendation(payload)
        if normalized.get("attractions"):
            return normalized
        city = _normalize_city(payload.get("city") or query)
        if city:
            return _build_recommendation_from_city(city=city, query=query)
        return normalized

    detail = get_attraction_info(attraction_name=query, location=None)
    return _normalize_info(detail)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run attraction sub-agent with a natural language query.")
    parser.add_argument(
        "query",
        type=str,
        nargs="?",
        help="Natural language query, e.g. 'Top attractions in Beijing'",
    )
    return parser


if __name__ == "__main__":
    parser = _build_cli_parser()
    args = parser.parse_args()
    if not args.query:
        parser.error("query is required. Example: python -m app.agents.attraction_agent 'Batu Caves ticket price'")

    response = run_attraction_agent(args.query)
    # Print JSON only so it can be consumed by parent agents/scripts directly.
    print(json.dumps(response, ensure_ascii=False, indent=2))
