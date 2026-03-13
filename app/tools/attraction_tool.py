import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
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

_FIXED_EXCHANGE_RATES: dict[str, float] = {
    "MYR": 1.0,
    "RM": 1.0,
    "CNY": 0.65,
    "RMB": 0.65,
    "USD": 4.70,
    "EUR": 5.10,
    "SGD": 3.50,
    "JPY": 0.031,
    "GBP": 6.00,
    "¥": 0.031,
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


def estimate_ticket_price(attraction_name: str, context_text: str = "") -> str | None:
    _ = attraction_name
    _ = context_text
    return None


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


def convert_to_myr(amount: float, currency: str) -> float | None:
    normalized_currency = currency.upper().strip()
    rate = _FIXED_EXCHANGE_RATES.get(normalized_currency)
    if rate is None:
        return None
    return round(float(amount) * rate, 2)


def _format_myr_amount(amount: float) -> str:
    return f"RM {amount:.2f}"


def _normalize_currency(value: str) -> str:
    upper = value.upper()
    if "MYR" in upper or re.search(r"\bRM\b", upper):
        return "MYR"
    if "USD" in upper:
        return "USD"
    if "CNY" in upper or "RMB" in upper:
        return "CNY"
    if "EUR" in upper:
        return "EUR"
    if "SGD" in upper:
        return "SGD"
    if "JPY" in upper:
        return "JPY"
    if "GBP" in upper:
        return "GBP"
    if "¥" in value:
        return "JPY"
    return ""


def _is_reliable_source_type(source_type: str) -> bool:
    return source_type in {"official", "government"}


def resolve_ticket_price(price_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    converted: list[dict[str, Any]] = []
    for candidate in price_candidates:
        amount = candidate.get("value")
        currency = _normalize_currency(_normalize_text(candidate.get("currency")))
        source_type = _normalize_text(candidate.get("source_type")).lower() or "third_party"
        url = _normalize_text(candidate.get("url"))
        if amount is None or not currency:
            continue
        try:
            numeric_amount = float(amount)
        except (TypeError, ValueError):
            continue

        myr_value = convert_to_myr(numeric_amount, currency)
        if myr_value is None:
            continue

        converted.append(
            {
                "value_myr": round(myr_value, 2),
                "source_type": source_type,
                "url": url,
            }
        )

    reliable_values = sorted(
        item["value_myr"] for item in converted if _is_reliable_source_type(item["source_type"])
    )
    if reliable_values:
        unique_values = sorted({round(v, 2) for v in reliable_values})
        if len(unique_values) == 1:
            return {
                "ticket_price": _format_myr_amount(unique_values[0]),
                "price_type": "exact",
                "price_note": "Official or government source",
            }
        return {
            "ticket_price": f"RM {unique_values[0]:.2f}-{unique_values[-1]:.2f}",
            "price_type": "range",
            "price_note": "Conflicting official/government prices",
        }

    third_party_values = sorted(item["value_myr"] for item in converted if item["source_type"] == "third_party")
    unique_third_party = sorted({round(v, 2) for v in third_party_values})
    if len(unique_third_party) > 1:
        return {
            "ticket_price": f"RM {unique_third_party[0]:.2f}-{unique_third_party[-1]:.2f}",
            "price_type": "range",
            "price_note": "Range derived from multiple non-official sources",
        }

    return {
        "ticket_price": None,
        "price_type": "unknown",
        "price_note": "Official price not found.",
    }


def _extract_price_candidates(text: str, source_type: str, url: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    patterns = [*_EXACT_PRICE_PATTERNS, *_FROM_PRICE_PATTERNS, *_RANGE_PRICE_PATTERNS]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(0).strip()
            currency = _normalize_currency(value)
            numbers = _extract_numbers(value)
            if not currency or not numbers:
                continue
            for number in numbers[:2]:
                candidates.append(
                    {
                        "value": number,
                        "currency": currency,
                        "source_type": source_type,
                        "url": url,
                    }
                )
    return candidates


def _infer_source_type(link: str) -> str:
    lowered = link.lower()
    if ".gov" in lowered or "tourism" in lowered and ".gov" in lowered:
        return "government"
    if any(token in lowered for token in ["official", "visit", "tickets", "admission"]):
        return "official"
    return "third_party"


def extract_ticket_price(text: str, attraction_name: str = "") -> dict[str, Any]:
    _ = attraction_name
    normalized = re.sub(r"https?://\S+", " ", text)
    normalized = re.sub(r"[?&](?:q|ved|sa|usg|ei|oq|aqs)=[^\s]+", " ", normalized, flags=re.IGNORECASE)
    candidates = _extract_price_candidates(normalized, source_type="third_party", url="")
    return resolve_ticket_price(candidates)


def convert_price_to_myr(text: str) -> str:
    candidates = _extract_price_candidates(text, source_type="third_party", url="")
    resolved = resolve_ticket_price(candidates)
    return _normalize_text(resolved.get("ticket_price"))


def normalize_ticket_price(text: str) -> str:
    return convert_price_to_myr(text)


def _is_valid_price_text(value: str) -> bool:
    if not value:
        return False
    value = value.strip()
    if len(value) < 6 or len(value) > 80:
        return False
    if re.search(r"[?&](?:q|ved|sa)=", value, re.IGNORECASE):
        return False
    if not re.search(r"\d", value):
        return False

    has_currency = re.search(r"(?:\bRM\b|\bMYR\b|\bUSD\b|\bCNY\b|\bRMB\b|\bEUR\b|\bSGD\b|\bJPY\b|\bGBP\b|¥)", value, re.IGNORECASE)
    return bool(has_currency)


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


def _http_get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 8) -> dict[str, Any] | list[Any] | None:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return None

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def fetch_wikipedia_summary(attraction_name: str, location: str | None = None) -> dict[str, str]:
    query = attraction_name.strip()
    if location:
        query = f"{query}, {location.strip()}"

    title = urllib.parse.quote(query.replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    data = _http_get_json(url, headers={"Accept": "application/json", "User-Agent": "ai-travel-assistant/1.0"})

    if not isinstance(data, dict) and location:
        fallback_title = urllib.parse.quote(attraction_name.strip().replace(" ", "_"))
        fallback_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{fallback_title}"
        data = _http_get_json(
            fallback_url,
            headers={"Accept": "application/json", "User-Agent": "ai-travel-assistant/1.0"},
        )

    if not isinstance(data, dict):
        return {"description": "", "image_url": "", "source_url": ""}

    page_url = _normalize_text(data.get("content_urls", {}).get("desktop", {}).get("page"))
    if not page_url:
        page_url = _normalize_text(data.get("content_urls", {}).get("mobile", {}).get("page"))

    return {
        "description": _normalize_text(data.get("extract")),
        "image_url": _normalize_text(data.get("thumbnail", {}).get("source")),
        "source_url": page_url,
    }


def fetch_nominatim_place(attraction_name: str, location: str | None = None) -> dict[str, Any]:
    query = f"{attraction_name} {location}".strip() if location else attraction_name.strip()
    if not query:
        return {}

    encoded_query = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&format=json&limit=1"
    data = _http_get_json(url, headers={"User-Agent": "ai-travel-assistant/1.0"})
    if not isinstance(data, list) or not data:
        return {}
    first = data[0] if isinstance(data[0], dict) else {}
    return {
        "display_name": _normalize_text(first.get("display_name")),
        "osm_url": f"https://www.openstreetmap.org/{_normalize_text(first.get('osm_type'))}/{_normalize_text(first.get('osm_id'))}"
        if first.get("osm_type") and first.get("osm_id")
        else "",
    }


def _collect_price_candidates_from_sources(sources: list[dict[str, str]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in sources:
        snippet = _normalize_text(source.get("snippet"))
        title = _normalize_text(source.get("title"))
        link = _normalize_text(source.get("link"))
        combined = f"{title} {snippet}".strip()
        if not combined:
            continue
        source_type = _infer_source_type(link)
        candidates.extend(_extract_price_candidates(combined, source_type=source_type, url=link))
    return candidates


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


def _is_valid_ticket_price_output(value: Any) -> bool:
    if value is None:
        return True
    text = _normalize_text(value)
    if not text:
        return False
    if not text.startswith("RM"):
        return False
    return bool(re.fullmatch(r"RM\s\d+(?:\.\d{2})?(?:-\d+(?:\.\d{2})?)?", text))


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
    attraction_name = attraction_name.strip()
    result: dict[str, Any] = {
        "query_type": "attraction_info",
        "name": attraction_name,
        "description": None,
        "image_url": None,
        "opening_hours": "",
        "visit_duration": "",
        "ticket_price": None,
        "price_type": "unknown",
        "price_note": "Official price not found.",
        "sources": [],
    }

    if not attraction_name:
        result["name"] = ""
        result["visit_duration"] = estimate_visit_duration(attraction_name)
        return result

    location_suffix = f" {location}" if location else ""
    cache_key = f"{attraction_name.lower()}::{(location or '').strip().lower()}"

    with _CACHE_LOCK:
        cache = _load_cache()
        cached = cache.get(cache_key)
        if cached and _is_cache_entry_usable(cached):
            return cached

    wiki_summary = fetch_wikipedia_summary(attraction_name=attraction_name, location=location)
    result["description"] = wiki_summary.get("description") or None
    result["image_url"] = wiki_summary.get("image_url") or None

    nominatim_result = fetch_nominatim_place(attraction_name=attraction_name, location=location)

    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    preferred_sources: list[dict[str, str]] = []
    all_organic: list[dict[str, Any]] = []
    image_data: dict[str, Any] = {}

    if api_key:
        queries = [
            f"{attraction_name}{location_suffix} opening hours",
            f"{attraction_name}{location_suffix} official ticket",
            f"{attraction_name}{location_suffix} admission fee",
            f"{attraction_name}{location_suffix} visit duration",
            f"{attraction_name}{location_suffix} official website",
        ]

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
                ]
            )
            for item in organic[:8]:
                text_blobs.append(_normalize_text(item.get("title")))
                text_blobs.append(_normalize_text(item.get("snippet")))

        preferred_sources = collect_preferred_sources(all_organic, min_count=3)
        source_text = "\n".join(
            f"{s.get('title', '')}\n{s.get('snippet', '')}\n{s.get('link', '')}" for s in preferred_sources
        )
        merged_text = "\n".join(t for t in [*text_blobs, source_text] if t)

        result["opening_hours"] = _extract_hours_from_sources(preferred_sources) or _extract_hours(merged_text)
        result["visit_duration"] = extract_visit_duration(merged_text, attraction_name)

        if not result["image_url"]:
            try:
                image_data = _search_google_images(f"{attraction_name}{location_suffix}", api_key)
            except Exception:
                image_data = {}
            result["image_url"] = _pick_image_url(all_organic, image_data) or None
    else:
        result["visit_duration"] = estimate_visit_duration(attraction_name)

    price_candidates = _collect_price_candidates_from_sources(preferred_sources)
    price_resolution = resolve_ticket_price(price_candidates)
    result.update(price_resolution)

    source_urls: list[str] = []
    if wiki_summary.get("source_url"):
        source_urls.append(wiki_summary["source_url"])
    if nominatim_result.get("osm_url"):
        source_urls.append(nominatim_result["osm_url"])
    for source in preferred_sources:
        link = _normalize_text(source.get("link"))
        if link:
            source_urls.append(link)

    deduped_sources: list[str] = []
    seen: set[str] = set()
    for url in source_urls:
        if url in seen:
            continue
        seen.add(url)
        deduped_sources.append(url)
    result["sources"] = deduped_sources[:6]

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
