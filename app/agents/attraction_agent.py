"""LangChain 子 Agent：处理景点推荐与景点详情查询。"""

from __future__ import annotations

import json
import os
import sys
import argparse
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
    """根据城市返回景点候选列表。"""
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
    """根据景点名（可选城市）返回景点详细信息。"""
    return get_attraction_info(attraction_name=attraction_name, location=location or None)


def _extract_json_object(text: str) -> dict[str, Any]:
    """从模型文本中提取 JSON 对象。"""
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


def _build_executor() -> Any:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY. Please set it in environment or .env before running.")

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        api_key=api_key,
        temperature=0,
    )

    tools = [attraction_recommendation_tool, attraction_detail_tool]
    system_prompt = (
        "你是 Attraction 子 Agent。你的职责是根据自然语言 query 在两类任务中做判断并调用工具："
        "1) attraction_recommendation（按城市推荐景点）；"
        "2) attraction_info（查询单个景点详情）。"
        "\n输出必须是严格 JSON 对象，不要 markdown，不要额外说明。"
        "\n推荐类输出格式："
        "{\"query_type\":\"attraction_recommendation\",\"city\":\"string\",\"attractions\":[{\"name\":\"string\"}],\"sources\":[]}"
        "\n详情类输出格式："
        "{\"query_type\":\"attraction_info\",\"name\":\"string\",\"opening_hours\":\"string\",\"visit_duration\":\"string\",\"ticket_price\":\"string\",\"sources\":[]}"
        "\n必须尽量调用工具获取信息，且所有字段都要存在。"
    )
    return create_agent(model=llm, tools=tools, system_prompt=system_prompt)


def run_attraction_agent(query: str) -> dict[str, Any]:
    """Attraction 子 Agent 统一入口。"""
    executor = _build_executor()
    result = executor.invoke({"messages": [("user", query)]})
    messages = result.get("messages", []) if isinstance(result, dict) else []
    output = messages[-1].content if messages else ""
    payload = _extract_json_object(output if isinstance(output, str) else json.dumps(output, ensure_ascii=False))

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
        help="Natural language query, e.g. '北京有什么好玩的景点'",
    )
    return parser


if __name__ == "__main__":
    parser = _build_cli_parser()
    args = parser.parse_args()
    if not args.query:
        parser.error("query is required. Example: python -m app.agents.attraction_agent 'Batu Caves 门票价格'")

    response = run_attraction_agent(args.query)
    # 只输出 JSON，便于主 Agent 或脚本直接消费。
    print(json.dumps(response, ensure_ascii=False, indent=2))
