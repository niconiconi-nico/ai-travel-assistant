import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from langchain.tools import tool
from serpapi import GoogleSearch

<<<<<<< HEAD
_CACHE_PATH = Path(__file__).with_name("attraction_cache.json")
_CACHE_LOCK = threading.Lock()


_CURRENCY_PATTERN = r"(?:RM|MYR|USD|US\$|\$|EUR|€|CNY|RMB|¥|SGD|HKD|GBP|£)\s?\d+(?:[\.,]\d{1,2})?(?:\s?(?:起|起价|per|/|每人|成人))?"
=======
# 缓存迁移到 app/data/attraction_cache.json
_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "attraction_cache.json"
_CACHE_LOCK = threading.Lock()

_CURRENCY_PATTERN = r"(?:RM|MYR|USD|US\$|\$|EUR|€|CNY|RMB|¥|SGD|HKD|GBP|£)\s?\d+(?:[\.,]\d{1,2})?(?:\s?(?:起|起价|per|/|每人|成人))?"
_PLATFORM_KEYWORDS = {
    "wikipedia": ["wikipedia.org", "wikipedia"],
    "tripadvisor": ["tripadvisor."],
    "google maps": ["maps.google", "google maps"],
    "klook": ["klook."],
}
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


<<<<<<< HEAD
def _load_cache() -> dict[str, dict[str, str]]:
=======
def _ensure_cache_dir() -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_cache() -> dict[str, dict[str, str]]:
    _ensure_cache_dir()
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict[str, dict[str, str]]) -> None:
<<<<<<< HEAD
=======
    _ensure_cache_dir()
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8
    _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_hours(text: str) -> str:
    patterns = [
<<<<<<< HEAD
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[^\n]{0,80}\d{1,2}[:.]?\d{0,2}\s?(?:AM|PM|am|pm)?[^\n]{0,80}",
        r"\d{1,2}[:.]\d{2}\s?(?:AM|PM|am|pm)?\s?(?:-|–|to|至)\s?\d{1,2}[:.]\d{2}\s?(?:AM|PM|am|pm)?",
        r"(?:open|opening\s*hours|营业时间|开放时间)[:：]?\s*[^\n\.;]{4,60}",
=======
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[^\n]{0,100}\d{1,2}[:.]?\d{0,2}\s?(?:AM|PM|am|pm)?[^\n]{0,100}",
        r"\d{1,2}[:.]\d{2}\s?(?:AM|PM|am|pm)?\s?(?:-|–|to|至)\s?\d{1,2}[:.]\d{2}\s?(?:AM|PM|am|pm)?",
        r"(?:open|opening\s*hours|营业时间|开放时间)[:：]?\s*[^\n\.;]{4,80}",
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _extract_ticket_price(text: str) -> str:
    match = re.search(_CURRENCY_PATTERN, text, re.IGNORECASE)
    if match:
        return match.group(0).strip()

    alt = re.search(r"(?:ticket|admission|price|fee|门票|票价)[:：]?\s*[^\n\.;]{0,40}", text, re.IGNORECASE)
    return alt.group(0).strip() if alt else ""


def _extract_duration(text: str) -> str:
    patterns = [
        r"\b\d+(?:\.\d+)?\s?(?:-|–|to)?\s?\d*(?:\.\d+)?\s?(?:hours?|hrs?|小时)\b",
        r"\b\d+\s?(?:minutes?|mins?|分钟)\b",
<<<<<<< HEAD
        r"(?:recommended\s*time|how\s*long\s*to\s*spend|visit\s*duration|建议游玩时长)[:：]?\s*[^\n\.;]{2,40}",
=======
        r"(?:recommended\s*time|how\s*long\s*to\s*spend|visit\s*duration|建议游玩时长|best\s*time\s*needed)[:：]?\s*[^\n\.;]{2,60}",
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


<<<<<<< HEAD
def _estimate_duration(attraction_name: str) -> str:
    name = attraction_name.lower()
    if any(k in name for k in ["museum", "博物馆", "gallery", "美术馆"]):
        return "2-3 hours (estimated)"
    if any(k in name for k in ["tower", "塔", "observation", "观景"]):
        return "1-2 hours (estimated)"
    if any(k in name for k in ["park", "公园", "garden", "植物园"]):
        return "2-4 hours (estimated)"
    if any(k in name for k in ["temple", "寺", "church", "mosque", "清真寺"]):
        return "1-2 hours (estimated)"
=======
def _estimate_duration(attraction_name: str, context_text: str = "") -> str:
    """基于景点名称 + 搜索文本做类型估算。"""
    combined = f"{attraction_name} {context_text}".lower()

    if any(k in combined for k in ["theme park", "amusement park", "water park", "游乐园", "主题乐园"]):
        return "4-6 hours (estimated)"
    if any(k in combined for k in ["museum", "博物馆", "gallery", "美术馆"]):
        return "2-3 hours (estimated)"
    if any(k in combined for k in ["park", "公园", "garden", "植物园"]):
        return "2-4 hours (estimated)"
    if any(k in combined for k in ["tower", "塔", "observation", "观景"]):
        return "1-2 hours (estimated)"
    if any(k in combined for k in ["temple", "寺", "church", "mosque", "清真寺"]):
        return "1-2 hours (estimated)"
    if any(k in combined for k in ["monument", "纪念碑", "memorial"]):
        return "1 hour (estimated)"
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8
    return "2 hours (estimated)"


def _pick_image_url(results: list[dict[str, Any]], image_results: dict[str, Any]) -> str:
    for result in results:
        for key in ("thumbnail", "image", "favicon"):
            val = _normalize_text(result.get(key))
            if val.startswith("http"):
                return val

    images = image_results.get("images_results", [])
    for item in images:
        original = _normalize_text(item.get("original"))
        thumb = _normalize_text(item.get("thumbnail"))
        if original.startswith("http"):
            return original
        if thumb.startswith("http"):
            return thumb
    return ""


def _search_google(query: str, api_key: str, num: int = 10) -> dict[str, Any]:
    params = {
        "engine": "google",
        "q": query,
        "hl": "en",
        "num": num,
        "api_key": api_key,
    }
    return GoogleSearch(params).get_dict()


def _search_google_images(query: str, api_key: str, num: int = 10) -> dict[str, Any]:
    params = {
        "engine": "google_images",
        "q": query,
        "hl": "en",
        "num": num,
        "api_key": api_key,
    }
    return GoogleSearch(params).get_dict()


<<<<<<< HEAD
def _collect_sources(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for item in results:
        title = _normalize_text(item.get("title"))
        link = _normalize_text(item.get("link"))
        snippet = _normalize_text(item.get("snippet") or item.get("snippet_highlighted_words"))
        if title or link or snippet:
            sources.append({"title": title, "link": link, "snippet": snippet})
        if len(sources) >= 6:
=======
def _is_platform_source(item: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            _normalize_text(item.get("title")).lower(),
            _normalize_text(item.get("link")).lower(),
            _normalize_text(item.get("snippet")).lower(),
        ]
    )
    return any(keyword in haystack for group in _PLATFORM_KEYWORDS.values() for keyword in group)


def _collect_sources(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()

    # 优先收集来自 Wikipedia / TripAdvisor / Google Maps / Klook 的结果
    prioritized = [item for item in results if _is_platform_source(item)] + [item for item in results if not _is_platform_source(item)]

    for item in prioritized:
        title = _normalize_text(item.get("title"))
        link = _normalize_text(item.get("link"))
        snippet = _normalize_text(item.get("snippet") or item.get("snippet_highlighted_words"))
        uniq_key = f"{title}|{link}"
        if uniq_key in seen:
            continue
        if title or link or snippet:
            sources.append({"title": title, "link": link, "snippet": snippet})
            seen.add(uniq_key)
        if len(sources) >= 8:
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8
            break
    return sources


def get_attraction_info(attraction_name: str, location: str | None = None) -> dict[str, Any]:
    api_key = os.getenv("SERPAPI_API_KEY")
    result: dict[str, Any] = {
        "name": attraction_name,
        "image_url": "",
        "opening_hours": "",
        "visit_duration": "",
        "ticket_price": "",
        "sources": [],
    }

    if not attraction_name.strip() or not api_key:
        if not attraction_name.strip():
            result["name"] = ""
        if not api_key:
            result["visit_duration"] = _estimate_duration(attraction_name)
        return result

    location_suffix = f" {location}" if location else ""
    cache_key = f"{attraction_name.strip().lower()}::{(location or '').strip().lower()}"

    with _CACHE_LOCK:
        cache = _load_cache()
        if cache_key in cache:
            return cache[cache_key]

    queries = [
        f"{attraction_name}{location_suffix} opening hours",
        f"{attraction_name}{location_suffix} ticket price",
<<<<<<< HEAD
        f"{attraction_name}{location_suffix} how long to spend",
=======
        f"{attraction_name}{location_suffix} admission fee",
        f"{attraction_name}{location_suffix} how long to spend",
        f"{attraction_name}{location_suffix} visit duration",
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8
        f"{attraction_name}{location_suffix} official website",
    ]

    all_organic: list[dict[str, Any]] = []
    text_blobs: list[str] = []

    for q in queries:
        try:
            data = _search_google(q, api_key)
        except Exception:
            continue

        kg = data.get("knowledge_graph", {})
        ab = data.get("answer_box", {})
        organic = data.get("organic_results", [])

        all_organic.extend(organic)
        text_blobs.extend([
            _normalize_text(kg),
            _normalize_text(ab),
            _normalize_text(data.get("sports_results")),
            _normalize_text(data.get("local_results")),
        ])
<<<<<<< HEAD
        for item in organic[:5]:
=======
        for item in organic[:8]:
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8
            text_blobs.append(_normalize_text(item.get("snippet")))

    image_data: dict[str, Any] = {}
    try:
        image_data = _search_google_images(f"{attraction_name}{location_suffix}", api_key)
    except Exception:
        image_data = {}

    merged_text = "\n".join(t for t in text_blobs if t)

    result["image_url"] = _pick_image_url(all_organic, image_data)
    result["opening_hours"] = _extract_hours(merged_text)
    result["ticket_price"] = _extract_ticket_price(merged_text)
<<<<<<< HEAD
    result["visit_duration"] = _extract_duration(merged_text) or _estimate_duration(attraction_name)
=======

    extracted_duration = _extract_duration(merged_text)
    result["visit_duration"] = extracted_duration or _estimate_duration(attraction_name, merged_text)
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8

    sources = _collect_sources(all_organic)
    if len(sources) < 3:
        images = image_data.get("images_results", [])
        for item in images:
            title = _normalize_text(item.get("title"))
            link = _normalize_text(item.get("link") or item.get("original"))
            snippet = _normalize_text(item.get("source"))
            if title or link:
                sources.append({"title": title, "link": link, "snippet": snippet})
            if len(sources) >= 3:
                break
<<<<<<< HEAD
    result["sources"] = sources[:6]
=======
    result["sources"] = sources[:8]
>>>>>>> 747d2c37196395b209f5f4f515a43c6eff22c1d8

    with _CACHE_LOCK:
        cache = _load_cache()
        cache[cache_key] = result
        _save_cache(cache)

    return result


@tool
def attraction_information_tool(attraction_name: str, location: str | None = None) -> dict[str, Any]:
    """
    景点信息工具：返回图片、营业时间、建议游玩时长、门票价格和可追溯来源。

    Args:
        attraction_name: 景点名称，例如 "Petronas Twin Towers"
        location: 可选地点，例如 "Kuala Lumpur"
    """

    return get_attraction_info(attraction_name=attraction_name, location=location)
