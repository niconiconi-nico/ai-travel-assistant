"""LangChain Attraction sub-agent for recommendations and attraction details."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from attraction_tool import get_attraction_info, get_attractions_by_place  # noqa: E402


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
        else:
            name = str(item).strip()
        if name:
            normalized_attractions.append({"name": name})

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

    return {
        "query_type": "attraction_info",
        "name": str(payload.get("name", "")).strip(),
        "opening_hours": str(payload.get("opening_hours", "")).strip(),
        "visit_duration": str(payload.get("visit_duration", "")).strip(),
        "ticket_price": str(payload.get("ticket_price", "")).strip(),
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
    executor = _build_executor()
    result = executor.invoke({"messages": [("user", query)]})
    messages = result.get("messages", []) if isinstance(result, dict) else []
    output = messages[-1].content if messages else ""
    payload = _extract_payload_from_output(output)

    query_type = str(payload.get("query_type", "")).strip()
    if query_type == "attraction_recommendation":
        return _normalize_recommendation(payload)
    if query_type == "attraction_info":
        return _normalize_info(payload)

    if "attractions" in payload or "city" in payload:
        return _normalize_recommendation(payload)
    return _normalize_info(payload)


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
