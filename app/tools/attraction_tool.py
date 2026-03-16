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
    if len(unique_third_party) == 1:
        return {
            "ticket_price": _format_myr_amount(unique_third_party[0]),
            "price_type": "exact",
            "price_note": "Single non-official source",
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



_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_GEOCODER_USER_AGENT = "ai-travel-assistant/1.0"


def _resolve_place_geometry(place: str) -> dict[str, Any]:
    query = _normalize_text(place)
    if not query:
        return {}

    encoded_query = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&format=json&limit=1"
    data = _http_get_json(url, headers={"User-Agent": _GEOCODER_USER_AGENT})
    if not isinstance(data, list) or not data:
        return {}

    first = data[0] if isinstance(data[0], dict) else {}
    bbox = first.get("boundingbox") if isinstance(first.get("boundingbox"), list) else []
    if len(bbox) == 4:
        try:
            south, north, west, east = map(float, bbox)
        except (TypeError, ValueError):
            south = north = west = east = None
    else:
        south = north = west = east = None

    try:
        lat = float(first.get("lat"))
        lon = float(first.get("lon"))
    except (TypeError, ValueError):
        return {}

    return {
        "lat": lat,
        "lon": lon,
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "display_name": _normalize_text(first.get("display_name")),
    }


def _run_overpass_query(query: str, timeout: int = 20) -> dict[str, Any]:
    payload = query.encode("utf-8")
    request = urllib.request.Request(
        _OVERPASS_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "User-Agent": _GEOCODER_USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_valid_entity_name(name: str) -> bool:
    text = _normalize_text(name)
    if len(text) < 3:
        return False
    lowered = text.lower()
    blocked_tokens = [
        "top ", "attractions", "things to do", "travel guide", "guide", "攻略", "景点玩乐", "必做事项", "washington georgetown",
    ]
    if any(token in lowered for token in blocked_tokens):
        return False
    if re.search(r"\b\d+\s*(?:best|top|大景点)\b", lowered):
        return False
    return True


def _normalize_opening_hours_value(value: str) -> str:
    cleaned = clean_opening_hours(value)
    return cleaned if cleaned and is_valid_opening_hours(cleaned) else ""


def _extract_ticket_price_from_tags(tags: dict[str, Any]) -> str:
    fee = _normalize_text(tags.get("fee") or tags.get("charge") or tags.get("price"))
    if not fee:
        return ""
    low = fee.lower()
    if low in {"no", "none", "unknown"}:
        return ""
    if low in {"yes", "paid"}:
        return ""
    if "free" in low or "免费" in fee:
        return "Free"

    normalized = convert_price_to_myr(fee)
    if normalized and normalized.startswith("RM"):
        return normalized
    if re.search(r"\bRM\b", fee, re.IGNORECASE):
        return fee.replace("MYR", "RM").strip()
    return ""


def _fetch_wikidata_entity(entity_id: str) -> dict[str, Any]:
    entity = _normalize_text(entity_id)
    if not entity:
        return {}
    url = (
        "https://www.wikidata.org/w/api.php?action=wbgetentities&ids="
        f"{urllib.parse.quote(entity)}&format=json&props=claims|descriptions|sitelinks"
    )
    data = _http_get_json(url, headers={"User-Agent": _GEOCODER_USER_AGENT})
    if not isinstance(data, dict):
        return {}
    entities = data.get("entities")
    if not isinstance(entities, dict):
        return {}
    payload = entities.get(entity)
    return payload if isinstance(payload, dict) else {}


def _extract_wikidata_image_url(entity_payload: dict[str, Any]) -> str:
    claims = entity_payload.get("claims") if isinstance(entity_payload.get("claims"), dict) else {}
    image_claims = claims.get("P18") if isinstance(claims.get("P18"), list) else []
    if not image_claims:
        return ""
    first = image_claims[0] if isinstance(image_claims[0], dict) else {}
    mainsnak = first.get("mainsnak") if isinstance(first.get("mainsnak"), dict) else {}
    datavalue = mainsnak.get("datavalue") if isinstance(mainsnak.get("datavalue"), dict) else {}
    filename = _normalize_text(datavalue.get("value"))
    if not filename:
        return ""
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(filename)}"


def _extract_wikidata_description(entity_payload: dict[str, Any]) -> str:
    descriptions = entity_payload.get("descriptions") if isinstance(entity_payload.get("descriptions"), dict) else {}
    for key in ("en", "zh", "zh-cn", "ms"):
        val = descriptions.get(key)
        if isinstance(val, dict):
            text = _normalize_text(val.get("value"))
            if text:
                return text
    return ""


def _normalize_wikipedia_title(value: str) -> str:
    text = _normalize_text(value)
    if text.startswith("en:"):
        return text[3:]
    return text


def _extract_poi_from_element(element: dict[str, Any]) -> dict[str, Any]:
    tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
    name = _normalize_text(tags.get("name"))
    if not _is_valid_entity_name(name):
        return {}

    poi: dict[str, Any] = {
        "name": name,
        "description": _normalize_text(tags.get("description") or tags.get("short_description")),
        "image": _normalize_text(tags.get("image")),
        "opening_hours": _normalize_opening_hours_value(_normalize_text(tags.get("opening_hours"))),
        "ticket_price": _extract_ticket_price_from_tags(tags),
        "wikipedia": _normalize_wikipedia_title(_normalize_text(tags.get("wikipedia"))),
        "wikidata": _normalize_text(tags.get("wikidata")),
        "website": _normalize_text(tags.get("website") or tags.get("url")),
        "osm_type": _normalize_text(element.get("type")),
        "osm_id": _normalize_text(element.get("id")),
    }
    if not poi["image"]:
        commons = _normalize_text(tags.get("wikimedia_commons"))
        if commons:
            poi["image"] = f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(commons)}"
    return poi


def _get_osm_city_pois(place: str, limit: int = 12) -> list[dict[str, Any]]:
    geo = _resolve_place_geometry(place)
    if not geo:
        return []

    lat = geo.get("lat")
    lon = geo.get("lon")
    if lat is None or lon is None:
        return []

    radius = 12000
    if isinstance(geo.get("south"), float) and isinstance(geo.get("north"), float):
        span_km = abs(float(geo["north"]) - float(geo["south"])) * 111
        if span_km > 0:
            radius = int(max(6000, min(22000, span_km * 700)))

    query = f"""
    [out:json][timeout:25];
    (
      nwr(around:{radius},{lat},{lon})[tourism=attraction];
      nwr(around:{radius},{lat},{lon})[tourism=museum];
      nwr(around:{radius},{lat},{lon})[tourism=viewpoint];
      nwr(around:{radius},{lat},{lon})[historic];
      nwr(around:{radius},{lat},{lon})[amenity=place_of_worship];
      nwr(around:{radius},{lat},{lon})[leisure=park];
    );
    out tags center 120;
    """

    data = _run_overpass_query(query)
    elements = data.get("elements") if isinstance(data.get("elements"), list) else []

    pois: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        poi = _extract_poi_from_element(element)
        if not poi:
            continue
        key = poi["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        pois.append(poi)
        if len(pois) >= limit:
            break
    return pois


def _search_osm_poi_by_name(name: str, location: str | None = None) -> dict[str, Any]:
    query = f"{name} {location}".strip() if location else name.strip()
    if not query:
        return {}

    encoded_query = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&format=json&limit=1"
    data = _http_get_json(url, headers={"User-Agent": _GEOCODER_USER_AGENT})
    if not isinstance(data, list) or not data:
        return {}

    first = data[0] if isinstance(data[0], dict) else {}
    osm_type = _normalize_text(first.get("osm_type"))
    osm_id = _normalize_text(first.get("osm_id"))
    if not osm_type or not osm_id:
        return {}

    overpass_type = {"node": "node", "way": "way", "relation": "relation"}.get(osm_type, "")
    if not overpass_type:
        return {}

    query_text = f"""
    [out:json][timeout:20];
    {overpass_type}({osm_id});
    out tags center 1;
    """
    data = _run_overpass_query(query_text)
    elements = data.get("elements") if isinstance(data.get("elements"), list) else []
    for element in elements:
        if isinstance(element, dict):
            poi = _extract_poi_from_element(element)
            if poi:
                return poi
    return {}


def _enrich_poi_with_knowledge(poi: dict[str, Any], location: str | None = None) -> dict[str, Any]:
    enriched = dict(poi)
    wiki_title = _normalize_text(enriched.get("wikipedia"))
    if not wiki_title:
        wiki_title = enriched.get("name", "")

    wiki = fetch_wikipedia_summary(wiki_title, location)
    if wiki.get("description") and not enriched.get("description"):
        enriched["description"] = wiki["description"]
    if wiki.get("image_url") and not enriched.get("image"):
        enriched["image"] = wiki["image_url"]

    wikidata_id = _normalize_text(enriched.get("wikidata"))
    if wikidata_id:
        entity = _fetch_wikidata_entity(wikidata_id)
        wd_desc = _extract_wikidata_description(entity)
        wd_image = _extract_wikidata_image_url(entity)
        if wd_desc and not enriched.get("description"):
            enriched["description"] = wd_desc
        if wd_image and not enriched.get("image"):
            enriched["image"] = wd_image

    source_urls = []
    osm_type = _normalize_text(enriched.get("osm_type"))
    osm_id = _normalize_text(enriched.get("osm_id"))
    if osm_type and osm_id:
        source_urls.append(f"https://www.openstreetmap.org/{osm_type}/{osm_id}")
    if wiki.get("source_url"):
        source_urls.append(wiki["source_url"])
    if enriched.get("website"):
        source_urls.append(_normalize_text(enriched.get("website")))

    deduped = []
    seen = set()
    for url in source_urls:
        if url and url not in seen:
            seen.add(url)
            deduped.append(url)
    enriched["sources"] = deduped[:5]
    return enriched

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
    _ = query_type
    place = _normalize_text(place)
    if not place:
        return []

    osm_pois = _get_osm_city_pois(place, limit=14)
    candidates: list[dict[str, str]] = []
    seen_names: set[str] = set()

    for poi in osm_pois:
        name = _normalize_text(poi.get("name"))
        if not _is_plausible_attraction_name(name):
            continue
        key = name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        desc = _normalize_text(poi.get("description")) or "Popular attraction in this destination."
        source = ""
        for src in poi.get("sources", []) if isinstance(poi.get("sources"), list) else []:
            source = _normalize_text(src)
            if source:
                break
        candidates.append({"name": name, "brief_description": desc, "source_link": source})
        if len(candidates) >= 12:
            return candidates

    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        return candidates

    base_queries = [
        f"{place} tourist attractions",
        f"{place} best attractions",
        f"{place} things to do",
        f"{place} 景点",
    ]

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
        "description": "",
        "image_url": "",
        "opening_hours": "",
        "visit_duration": "",
        "ticket_price": "",
        "price_type": "unknown",
        "price_note": "Official price not found.",
        "sources": [],
    }

    if not attraction_name:
        result["name"] = ""
        result["visit_duration"] = estimate_visit_duration(attraction_name)
        return result

    cache_key = f"{attraction_name.lower()}::{(location or '').strip().lower()}"
    with _CACHE_LOCK:
        cache = _load_cache()
        cached = cache.get(cache_key)
        if cached and _is_cache_entry_usable(cached):
            return cached

    # OSM/Wikipedia/Wikidata first
    poi = _search_osm_poi_by_name(attraction_name, location)
    if poi:
        poi = _enrich_poi_with_knowledge(poi, location)
        result["name"] = _normalize_text(poi.get("name")) or attraction_name
        result["description"] = _normalize_text(poi.get("description"))
        result["image_url"] = _normalize_text(poi.get("image"))
        result["opening_hours"] = _normalize_opening_hours_value(_normalize_text(poi.get("opening_hours")))
        result["ticket_price"] = _normalize_text(poi.get("ticket_price"))
        result["sources"] = poi.get("sources", []) if isinstance(poi.get("sources"), list) else []

    if not result["description"] or not result["image_url"]:
        wiki_summary = fetch_wikipedia_summary(attraction_name=attraction_name, location=location)
        if wiki_summary.get("description") and not result["description"]:
            result["description"] = wiki_summary.get("description", "")
        if wiki_summary.get("image_url") and not result["image_url"]:
            result["image_url"] = wiki_summary.get("image_url", "")
        if wiki_summary.get("source_url"):
            result["sources"].append(wiki_summary["source_url"])

    nominatim_result = fetch_nominatim_place(attraction_name=attraction_name, location=location)
    if nominatim_result.get("osm_url"):
        result["sources"].append(nominatim_result["osm_url"])

    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    preferred_sources: list[dict[str, str]] = []
    all_organic: list[dict[str, Any]] = []

    if api_key:
        location_suffix = f" {location}" if location else ""
        queries = [
            f"{attraction_name}{location_suffix} official ticket",
            f"{attraction_name}{location_suffix} admission fee",
            f"{attraction_name}{location_suffix} opening hours",
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
            text_blobs.extend([
                _normalize_text(data.get("knowledge_graph")),
                _normalize_text(data.get("answer_box")),
            ])
            for item in organic[:8]:
                text_blobs.append(_normalize_text(item.get("title")))
                text_blobs.append(_normalize_text(item.get("snippet")))

        preferred_sources = collect_preferred_sources(all_organic, min_count=3)
        merged_text = "\n".join(t for t in text_blobs if t)

        if not result["opening_hours"]:
            result["opening_hours"] = _extract_hours_from_sources(preferred_sources) or _extract_hours(merged_text)
        if not result["ticket_price"]:
            price_candidates = _collect_price_candidates_from_sources(preferred_sources)
            price_resolution = resolve_ticket_price(price_candidates)
            result["ticket_price"] = _normalize_text(price_resolution.get("ticket_price"))
            result["price_type"] = _normalize_text(price_resolution.get("price_type")) or "unknown"
            result["price_note"] = _normalize_text(price_resolution.get("price_note")) or "Official price not found."

        if not result["image_url"]:
            try:
                image_data = _search_google_images(f"{attraction_name}{location_suffix}", api_key)
            except Exception:
                image_data = {}
            result["image_url"] = _pick_image_url(all_organic, image_data)

        for source in preferred_sources:
            link = _normalize_text(source.get("link"))
            if link:
                result["sources"].append(link)

    if not result["visit_duration"]:
        result["visit_duration"] = estimate_visit_duration(attraction_name, result.get("description", ""))

    result["opening_hours"] = _normalize_opening_hours_value(result.get("opening_hours", ""))
    if not _is_valid_ticket_price_output(result.get("ticket_price")):
        if _normalize_text(result.get("ticket_price")) == "Free":
            pass
        else:
            result["ticket_price"] = ""

    deduped_sources: list[str] = []
    seen: set[str] = set()
    for url in result.get("sources", []):
        text = _normalize_text(url)
        if not text or text in seen:
            continue
        seen.add(text)
        deduped_sources.append(text)
    result["sources"] = deduped_sources[:8]

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
