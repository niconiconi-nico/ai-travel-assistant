import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from langchain.tools import tool
from serpapi import GoogleSearch

_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "attraction_cache.json"
_CACHE_LOCK = threading.Lock()

_EXACT_PRICE_PATTERNS = [
    r"(?:RM|MYR)\s+\d+(?:[\.,]\d{1,2})?",
    r"USD\s+\d+(?:[\.,]\d{1,2})?",
    r"(?:CNY|RMB)\s+\d+(?:[\.,]\d{1,2})?",
    r"[¥]\s?\d+(?:[\.,]\d{1,2})?",
]
_FROM_PRICE_PATTERNS = [
    r"(?:from|starting\s+from|adult\s+ticket)\s*(?:at\s*)?(?:RM|MYR|USD|CNY|RMB|¥)\s?\d+(?:[\.,]\d{1,2})?",
    r"(?:成人票|起价|起)\s*(?:RM|MYR|USD|CNY|RMB|¥)?\s?\d+(?:[\.,]\d{1,2})?",
]
_RANGE_PRICE_PATTERNS = [
    r"(?:RM|MYR|USD|CNY|RMB|¥)\s?\d+(?:[\.,]\d{1,2})?\s?(?:-|–|to|~|～)\s?(?:RM|MYR|USD|CNY|RMB|¥)?\s?\d+(?:[\.,]\d{1,2})?",
    r"\d+(?:[\.,]\d{1,2})?\s?(?:-|–|to|~|～)\s?\d+(?:[\.,]\d{1,2})?\s?(?:元|RMB|CNY|¥|RM|MYR|USD)",
]
_FREE_PRICE_PATTERNS = [r"\bfree\b", r"free\s+entry", r"possibly\s+free", r"免票", r"免费"]

_PLATFORM_PRIORITIES = {
    "official": 100,
    "wikipedia": 90,
    "tripadvisor": 85,
    "trip": 80,
    "klook": 78,
    "travel_guide": 72,
    "google_maps": 70,
    "kkday": 65,
    "ctrip": 65,
    "other": 20,
}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _load_cache() -> dict[str, dict[str, Any]]:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def is_valid_opening_hours(text: str) -> bool:
    if not text:
        return False

    value = text.strip()
    if len(value) < 4 or len(value) > 120:
        return False

    blocked_patterns = [r"\?q=", r"&sa=", r"&ved=", r"http", r"https", r"<[^>]+>"]
    if any(re.search(pat, value, re.IGNORECASE) for pat in blocked_patterns):
        return False

    if re.search(r"[A-Za-z0-9_-]{30,}", value):
        return False

    has_time = bool(
        re.search(
            r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s?(?:AM|PM|am|pm)\b|\b\d{1,2}(?::\d{2})?\s?(?:-|–|to|至)\s?\d{1,2}(?::\d{2})?\s?(?:AM|PM|am|pm)?\b",
            value,
            re.IGNORECASE,
        )
    )
    has_day_or_month = bool(
        re.search(
            r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun|January|February|March|April|May|June|July|August|September|October|November|December",
            value,
            re.IGNORECASE,
        )
    )
    has_hours_keyword = bool(re.search(r"opening\s*hours|open|closed|营业时间|开放时间", value, re.IGNORECASE))

    if has_time:
        return True
    if has_day_or_month and has_hours_keyword:
        return True
    return False


def clean_opening_hours(text: str) -> str:
    if not text:
        return ""

    cleaned = re.sub(r"https?://\S+", " ", text)
    cleaned = re.sub(r"[?&](?:q|ved|sa|usg|ei|oq|aqs)=[^\s]+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)

    chunks = re.split(r"[\n;。]+", cleaned)
    for chunk in chunks:
        candidate = " ".join(chunk.split()).strip(" -|,。\t")
        if is_valid_opening_hours(candidate):
            return candidate
    return ""


def _extract_hours_from_sources(sources: list[dict[str, str]]) -> str:
    for src in sources:
        snippet = _normalize_text(src.get("snippet"))
        title = _normalize_text(src.get("title"))
        candidate = clean_opening_hours(f"{title}. {snippet}")
        if candidate:
            return candidate
    return ""


def _extract_hours(text: str) -> str:
    cleaned = clean_opening_hours(text)
    if cleaned:
        return cleaned

    patterns = [
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[^\n]{0,120}\d{1,2}[:.]?\d{0,2}\s?(?:AM|PM|am|pm)?[^\n]{0,120}",
        r"\d{1,2}[:.]\d{2}\s?(?:AM|PM|am|pm)?\s?(?:-|–|to|至)\s?\d{1,2}[:.]\d{2}\s?(?:AM|PM|am|pm)?",
        r"(?:open|opening\s*hours|营业时间|开放时间|Closed\s+on)[:：]?\s*[^\n\.;]{4,80}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = clean_opening_hours(match.group(0))
            if candidate:
                return candidate
    return ""


def _detect_attraction_type(name: str, text: str = "") -> str:
    corpus = f"{name} {text}".lower()
    rules = [
        ("theme_park", ["theme park", "amusement", "游乐园", "主题公园"]),
        ("museum", ["museum", "gallery", "博物馆", "美术馆"]),
        ("zoo_aquarium", ["zoo", "aquarium", "海洋馆", "动物园"]),
        ("shopping_old_town", ["old town", "shopping street", "古镇", "步行街", "老街"]),
        ("tower", ["tower", "observation", "塔", "观景"]),
        ("temple", ["temple", "church", "mosque", "寺", "教堂", "清真寺"]),
        ("park", ["park", "garden", "植物园", "公园"]),
        ("palace_historic", ["palace", "historic", "fort", "古迹", "宫殿", "遗址"]),
        ("monument", ["monument", "memorial", "statue", "纪念碑", "雕像"]),
    ]
    for attraction_type, keywords in rules:
        if any(keyword in corpus for keyword in keywords):
            return attraction_type
    return "generic"


def estimate_ticket_price(attraction_name: str, context_text: str = "") -> str:
    attraction_type = _detect_attraction_type(attraction_name, context_text)
    estimates = {
        "museum": "RM 20–RM 50 (estimated)",
        "theme_park": "RM 150+ (estimated)",
        "tower": "RM 40–RM 120 (estimated)",
        "temple": "RM 0–RM 20 (estimated)",
        "park": "RM 0–RM 10 (estimated)",
        "palace_historic": "RM 20–RM 80 (estimated)",
        "monument": "RM 10–RM 40 (estimated)",
        "zoo_aquarium": "RM 30–RM 120 (estimated)",
        "shopping_old_town": "RM 0–RM 50 (estimated)",
        "generic": "RM 20–RM 80 (estimated)",
    }
    return estimates.get(attraction_type, estimates["generic"])


def estimate_visit_duration(attraction_name: str, context_text: str = "") -> str:
    attraction_type = _detect_attraction_type(attraction_name, context_text)
    estimates = {
        "theme_park": "4-6 hours (estimated)",
        "museum": "2-3 hours (estimated)",
        "park": "2-4 hours (estimated)",
        "tower": "1-2 hours (estimated)",
        "temple": "1-2 hours (estimated)",
        "monument": "1 hour (estimated)",
        "zoo_aquarium": "2-4 hours (estimated)",
        "shopping_old_town": "2-3 hours (estimated)",
        "generic": "2 hours (estimated)",
    }
    return estimates.get(attraction_type, estimates["generic"])


def _extract_numbers(value: str) -> list[float]:
    nums = re.findall(r"\d+(?:[\.,]\d+)?", value)
    return [float(n.replace(",", "")) for n in nums]


def _to_myr(value: float, currency: str) -> int:
    currency = currency.upper()
    if currency in {"RM", "MYR"}:
        return int(round(value))
    if currency in {"USD"}:
        return int(round(value * 4.7))
    if currency in {"CNY", "RMB", "¥"}:
        return int(round(value * 0.65))
    return int(round(value))


def _detect_currency(value: str) -> str:
    upper = value.upper()
    if "MYR" in upper:
        return "MYR"
    if re.search(r"\bRM\b", upper):
        return "RM"
    if "USD" in upper:
        return "USD"
    if "CNY" in upper or "RMB" in upper:
        return "CNY"
    if "¥" in value:
        return "¥"
    return ""


def _normalize_price_to_myr(value: str) -> str:
    if not value:
        return ""
    if value.lower() == "free":
        return "Free"

    currency = _detect_currency(value)
    numbers = _extract_numbers(value)
    if not currency or not numbers:
        return ""

    if currency in {"RM", "MYR"}:
        if len(numbers) >= 2 and re.search(r"-|–|to|~|～", value):
            return f"RM {int(round(numbers[0]))}–RM {int(round(numbers[1]))}"
        if any(k in value.lower() for k in ["from", "starting", "adult", "起价", "起", "成人票"]):
            return f"From RM {int(round(numbers[0]))}"
        return f"RM {int(round(numbers[0]))}"

    converted = [_to_myr(num, currency) for num in numbers[:2]]
    if len(converted) >= 2 and re.search(r"-|–|to|~|～", value):
        return f"RM {converted[0]}–RM {converted[1]} (estimated)"
    return f"RM {converted[0]} (estimated)"




def is_valid_ticket_price(text: str) -> bool:
    return _is_valid_price_text(text)


def convert_price_to_myr(text: str) -> str:
    return _normalize_price_to_myr(text)


def normalize_ticket_price(text: str) -> str:
    return _normalize_price_to_myr(text)


def _is_valid_price_text(value: str) -> bool:
    if not value:
        return False
    value = value.strip()
    if len(value) < 6 or len(value) > 50:
        return False
    if re.search(r"[?&](?:q|ved|sa)=", value, re.IGNORECASE):
        return False
    if not re.search(r"\d", value):
        return False

    has_currency = re.search(r"(?:\bRM\b|\bMYR\b|\bUSD\b|\bCNY\b|\bRMB\b|¥)", value, re.IGNORECASE)
    if not has_currency:
        return False

    # 显式过滤错误样本 rM7 / RM7
    if re.fullmatch(r"(?i)rm\d{1,3}", value.strip()):
        return False

    # 货币代码后必须有空格（避免粘连乱码）
    if re.search(r"(?i)\b(?:RM|MYR|USD|CNY|RMB)\d", value):
        return False

    return True


def extract_ticket_price(text: str, attraction_name: str = "") -> str:
    normalized = re.sub(r"https?://\S+", " ", text)
    normalized = re.sub(r"[?&](?:q|ved|sa|usg|ei|oq|aqs)=[^\s]+", " ", normalized, flags=re.IGNORECASE)

    # 1) 精确价格
    for pattern in _EXACT_PRICE_PATTERNS:
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            candidate = match.group(0).strip()
            if is_valid_ticket_price(candidate):
                normalized_price = normalize_ticket_price(candidate)
                if normalized_price:
                    return normalized_price

    # 2) 起价
    for pattern in _FROM_PRICE_PATTERNS:
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            candidate = match.group(0).strip()
            if is_valid_ticket_price(candidate):
                normalized_price = normalize_ticket_price(candidate)
                if normalized_price:
                    return normalized_price

    # 3) 区间
    for pattern in _RANGE_PRICE_PATTERNS:
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            candidate = match.group(0).strip()
            if is_valid_ticket_price(candidate):
                normalized_price = normalize_ticket_price(candidate)
                if normalized_price:
                    return normalized_price

    # 4) 免费
    for pattern in _FREE_PRICE_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return "Free"

    # 5) 估计价格（统一 MYR）
    return estimate_ticket_price(attraction_name, text)


def extract_visit_duration(text: str, attraction_name: str = "") -> str:
    patterns = [
        r"\b\d+(?:\.\d+)?\s?(?:-|–|to|~)?\s?\d*(?:\.\d+)?\s?(?:hours?|hrs?|小时)\b",
        r"\b\d+\s?(?:minutes?|mins?|分钟)\b",
        r"(?:recommended\s*time|how\s*long\s*to\s*spend|visit\s*duration|建议游玩时长)[:：]?\s*[^\n\.;]{2,60}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return estimate_visit_duration(attraction_name, text)


def _pick_image_url(results: list[dict[str, Any]], image_results: dict[str, Any]) -> str:
    for result in results:
        for key in ("thumbnail", "image", "favicon"):
            value = _normalize_text(result.get(key))
            if value.startswith("http"):
                return value

    for image in image_results.get("images_results", []):
        original = _normalize_text(image.get("original"))
        thumbnail = _normalize_text(image.get("thumbnail"))
        if original.startswith("http"):
            return original
        if thumbnail.startswith("http"):
            return thumbnail
    return ""


def _search_google(query: str, api_key: str, num: int = 10) -> dict[str, Any]:
    params = {"engine": "google", "q": query, "hl": "en", "num": num, "api_key": api_key}
    return GoogleSearch(params).get_dict()


def _search_google_images(query: str, api_key: str, num: int = 10) -> dict[str, Any]:
    params = {"engine": "google_images", "q": query, "hl": "en", "num": num, "api_key": api_key}
    return GoogleSearch(params).get_dict()


def _classify_platform(link: str, title: str = "") -> str:
    haystack = f"{link} {title}".lower()
    if any(x in haystack for x in ["official", ".gov", ".edu"]):
        return "official"
    if "wikipedia.org" in haystack:
        return "wikipedia"
    if "tripadvisor" in haystack:
        return "tripadvisor"
    if "trip.com" in haystack:
        return "trip"
    if "klook" in haystack:
        return "klook"
    if any(x in haystack for x in ["travel guide", "lonely planet", "wikivoyage", "guide"]):
        return "travel_guide"
    if "google.com/maps" in haystack or "maps.google" in haystack:
        return "google_maps"
    if "kkday" in haystack:
        return "kkday"
    if "ctrip" in haystack or "携程" in haystack:
        return "ctrip"
    return "other"


def collect_preferred_sources(results: list[dict[str, Any]], min_count: int = 3) -> list[dict[str, str]]:
    ranked: list[tuple[int, dict[str, str]]] = []
    seen_links: set[str] = set()

    for item in results:
        title = _normalize_text(item.get("title"))
        link = _normalize_text(item.get("link"))
        snippet = _normalize_text(item.get("snippet") or item.get("snippet_highlighted_words"))
        if not (title or link or snippet):
            continue

        dedup_key = link or title.lower()
        if dedup_key in seen_links:
            continue
        seen_links.add(dedup_key)

        platform = _classify_platform(link, title)
        score = _PLATFORM_PRIORITIES.get(platform, _PLATFORM_PRIORITIES["other"])
        ranked.append((score, {"title": title, "link": link, "snippet": snippet}))

    ranked.sort(key=lambda x: x[0], reverse=True)
    sources = [item for _, item in ranked[:6]]
    return sources[: max(3, min_count)] if len(sources) >= 3 else sources


def _is_plausible_attraction_name(name: str) -> bool:
    text = name.strip()
    if len(text) < 3:
        return False
    bad_tokens = [
        "things to do",
        "best attractions",
        "tripadvisor",
        "wikipedia",
        "official site",
        "guide",
        "攻略",
        "门票",
        "票价",
    ]
    lowered = text.lower()
    if any(token in lowered for token in bad_tokens):
        return False
    if re.search(r"\b\d{4}\b", text):
        return False
    return True


def get_attractions_by_place(place: str, query_type: str | None = None) -> list[dict[str, str]]:
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    place = _normalize_text(place)
    if not place or not api_key:
        return []

    base_queries = [
        f"{place} tourist attractions",
        f"{place} best attractions",
        f"{place} things to do",
        f"{place} 景点",
        f"{place} 必去景点",
        f"{place} 旅游攻略",
    ]
    if query_type:
        base_queries.insert(0, f"{place} {query_type}")

    candidates: list[dict[str, str]] = []
    seen_names: set[str] = set()

    for query in base_queries:
        try:
            payload = _search_google(query, api_key)
        except Exception:
            continue

        for item in payload.get("organic_results", [])[:10]:
            title = _normalize_text(item.get("title"))
            link = _normalize_text(item.get("link"))
            snippet = _normalize_text(item.get("snippet"))

            name = re.split(r"\s[-|–]\s", title)[0].strip() if title else ""
            if not _is_plausible_attraction_name(name):
                continue

            name_key = name.lower()
            if name_key in seen_names:
                continue
            seen_names.add(name_key)

            candidates.append(
                {
                    "name": name,
                    "brief_description": snippet or "Popular attraction in this destination.",
                    "source_link": link,
                }
            )
            if len(candidates) >= 12:
                return candidates

    return candidates


def _is_valid_ticket_price_output(value: str) -> bool:
    if not value:
        return False
    if value == "Free":
        return True
    if "estimated" in value.lower() and value.startswith("RM"):
        return True
    if not value.startswith("RM") and not value.startswith("From RM"):
        return False
    return bool(re.search(r"\d", value))


def _is_cache_entry_usable(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    opening_hours = _normalize_text(entry.get("opening_hours"))
    ticket_price = _normalize_text(entry.get("ticket_price"))

    if opening_hours and not is_valid_opening_hours(opening_hours):
        return False
    if ticket_price and not _is_valid_ticket_price_output(ticket_price):
        return False
    return True



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
        result["visit_duration"] = estimate_visit_duration(attraction_name)
        result["ticket_price"] = estimate_ticket_price(attraction_name)
        return result

    location_suffix = f" {location}" if location else ""
    cache_key = f"{attraction_name.strip().lower()}::{(location or '').strip().lower()}"

    with _CACHE_LOCK:
        cache = _load_cache()
        cached = cache.get(cache_key)
        if cached and _is_cache_entry_usable(cached):
            return cached

    queries = [
        f"{attraction_name}{location_suffix} opening hours",
        f"{attraction_name}{location_suffix} ticket price",
        f"{attraction_name}{location_suffix} admission fee",
        f"{attraction_name}{location_suffix} entry fee",
        f"{attraction_name}{location_suffix} adult ticket",
        f"{attraction_name}{location_suffix} official ticket",
        f"{attraction_name}{location_suffix} 门票",
        f"{attraction_name}{location_suffix} 票价",
        f"{attraction_name}{location_suffix} 成人票",
        f"{attraction_name}{location_suffix} 多少钱",
        f"{attraction_name}{location_suffix} how long to spend",
        f"{attraction_name}{location_suffix} visit duration",
        f"{attraction_name}{location_suffix} official website",
    ]

    all_organic: list[dict[str, Any]] = []
    text_blobs: list[str] = []

    for query in queries:
        try:
            data = _search_google(query, api_key)
        except Exception:
            continue

        organic = data.get("organic_results", [])
        all_organic.extend(organic)

        text_blobs.extend(
            [
                _normalize_text(data.get("knowledge_graph")),
                _normalize_text(data.get("answer_box")),
                _normalize_text(data.get("local_results")),
                _normalize_text(data.get("sports_results")),
            ]
        )
        for item in organic[:8]:
            text_blobs.append(_normalize_text(item.get("title")))
            text_blobs.append(_normalize_text(item.get("snippet")))

    image_data: dict[str, Any] = {}
    try:
        image_data = _search_google_images(f"{attraction_name}{location_suffix}", api_key)
    except Exception:
        image_data = {}

    preferred_sources = collect_preferred_sources(all_organic, min_count=3)
    source_text = "\n".join(
        f"{s.get('title', '')}\n{s.get('snippet', '')}\n{s.get('link', '')}" for s in preferred_sources
    )
    merged_text = "\n".join(t for t in [*text_blobs, source_text] if t)

    result["image_url"] = _pick_image_url(all_organic, image_data)
    result["opening_hours"] = _extract_hours_from_sources(preferred_sources) or _extract_hours(merged_text)
    result["ticket_price"] = extract_ticket_price(merged_text, attraction_name)
    result["visit_duration"] = extract_visit_duration(merged_text, attraction_name)

    sources = preferred_sources
    if len(sources) < 3:
        for image in image_data.get("images_results", []):
            title = _normalize_text(image.get("title"))
            link = _normalize_text(image.get("link") or image.get("original"))
            snippet = _normalize_text(image.get("source"))
            if title or link:
                sources.append({"title": title, "link": link, "snippet": snippet})
            if len(sources) >= 3:
                break
    result["sources"] = sources[:6]

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
