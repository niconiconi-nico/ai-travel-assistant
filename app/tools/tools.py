from importlib import import_module
from importlib.util import find_spec
import json
import os
from datetime import date, datetime, time, timedelta

from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


TRAVEL_ATTRACTION_CATALOG = {
    "bangkok": [
        {
            "name": "The Grand Palace",
            "location": "Phra Nakhon, Bangkok",
            "information": "泰国皇室地标，建筑华丽",
            "price": 500.00,
            "currency": "THB",
            "open_time": "08:30-15:30",
            "suggested_duration_hours": 3,
            "preferred_start_time": "09:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/c/c4/Grand_Palace_Bangkok.jpg",
        },
        {
            "name": "Wat Pho",
            "location": "Phra Nakhon, Bangkok",
            "information": "卧佛闻名，寺院历史悠久",
            "price": 300.00,
            "currency": "THB",
            "open_time": "08:00-18:30",
            "suggested_duration_hours": 2,
            "preferred_start_time": "13:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/1/1e/Wat_Pho_Bangkok.jpg",
        },
        {
            "name": "Wat Arun",
            "location": "Bangkok Yai, Bangkok",
            "information": "郑王庙临河，夕景迷人",
            "price": 200.00,
            "currency": "THB",
            "open_time": "08:00-18:00",
            "suggested_duration_hours": 2,
            "preferred_start_time": "16:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/a/a1/Wat_Arun_Bangkok.jpg",
        },
        {
            "name": "Jim Thompson House Museum",
            "location": "Pathum Wan, Bangkok",
            "information": "泰丝名宅，艺术氛围浓厚",
            "price": 200.00,
            "currency": "THB",
            "open_time": "10:00-18:00",
            "suggested_duration_hours": 2,
            "preferred_start_time": "10:30",
            "image": "https://upload.wikimedia.org/wikipedia/commons/9/95/Jim_Thompson_House.jpg",
        },
        {
            "name": "Chatuchak Weekend Market",
            "location": "Chatuchak, Bangkok",
            "information": "大型市集，购物美食丰富",
            "price": 0.00,
            "currency": "THB",
            "open_time": "09:00-18:00",
            "suggested_duration_hours": 3,
            "preferred_start_time": "14:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/d/d5/Chatuchak_Market_Bangkok.jpg",
        },
    ],
    "pattaya": [
        {
            "name": "Sanctuary of Truth",
            "location": "Na Kluea, Pattaya",
            "information": "全木雕神殿，工艺震撼",
            "price": 500.00,
            "currency": "THB",
            "open_time": "08:00-18:00",
            "suggested_duration_hours": 3,
            "preferred_start_time": "09:30",
            "image": "https://upload.wikimedia.org/wikipedia/commons/8/82/Sanctuary_of_Truth_Pattaya.jpg",
        },
        {
            "name": "Nong Nooch Tropical Garden",
            "location": "Sattahip, Pattaya",
            "information": "热带园林秀，亲子热门",
            "price": 600.00,
            "currency": "THB",
            "open_time": "08:00-18:00",
            "suggested_duration_hours": 3,
            "preferred_start_time": "13:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/0/06/Nong_Nooc_Tropical_Garden.jpg",
        },
        {
            "name": "Pattaya Floating Market",
            "location": "Bang Lamung, Pattaya",
            "information": "水上市集，体验泰式风情",
            "price": 200.00,
            "currency": "THB",
            "open_time": "09:00-19:00",
            "suggested_duration_hours": 2,
            "preferred_start_time": "10:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/2/22/Pattaya_Floating_Market.jpg",
        },
        {
            "name": "Big Buddha Temple",
            "location": "South Pattaya, Pattaya",
            "information": "山顶大佛，俯瞰芭堤雅湾",
            "price": 100.00,
            "currency": "THB",
            "open_time": "07:00-19:00",
            "suggested_duration_hours": 1,
            "preferred_start_time": "16:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/7/71/Wat_Phra_Yai_Pattaya.jpg",
        },
        {
            "name": "Art in Paradise Pattaya",
            "location": "North Pattaya, Pattaya",
            "information": "互动3D美术馆，拍照有趣",
            "price": 400.00,
            "currency": "THB",
            "open_time": "09:00-21:00",
            "suggested_duration_hours": 2,
            "preferred_start_time": "13:30",
            "image": "https://upload.wikimedia.org/wikipedia/commons/9/92/Art_in_Paradise_Pattaya.jpg",
        },
    ],
    "tokyo": [
        {
            "name": "Tokyo Tower",
            "location": "Minato, Tokyo",
            "information": "东京经典观景塔，适合俯瞰城市天际线。",
            "price": 1500.00,
            "currency": "JPY",
            "open_time": "09:00-22:30",
            "suggested_duration_hours": 2,
            "preferred_start_time": "17:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/3/37/Tokyo_Tower_and_around_Skyscrapers.jpg",
        },
        {
            "name": "Sensō-ji",
            "location": "Asakusa, Tokyo",
            "information": "浅草地标寺院，适合第一次到东京的游客。",
            "price": 0.00,
            "currency": "JPY",
            "open_time": "06:00-17:00",
            "suggested_duration_hours": 2,
            "preferred_start_time": "09:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/a/a5/Sensoji_2023.jpg",
        },
        {
            "name": "Meiji Shrine",
            "location": "Shibuya, Tokyo",
            "information": "位于森林步道中的神社，氛围安静。",
            "price": 0.00,
            "currency": "JPY",
            "open_time": "06:00-18:00",
            "suggested_duration_hours": 2,
            "preferred_start_time": "10:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/8/89/Meiji_Shrine_Honden_2023.jpg",
        },
        {
            "name": "Shibuya Scramble Crossing",
            "location": "Shibuya, Tokyo",
            "information": "东京最具代表性的都市街景之一，白天夜晚都适合打卡。",
            "price": 0.00,
            "currency": "JPY",
            "open_time": "00:00-23:59",
            "suggested_duration_hours": 1,
            "preferred_start_time": "19:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/5/5d/Shibuya_Night_%282018%29.jpg",
        },
    ],
    "singapore": [
        {
            "name": "Gardens by the Bay",
            "location": "Marina Bay, Singapore",
            "information": "滨海湾超级树与温室花园，是新加坡最热门地标之一。",
            "price": 0.00,
            "currency": "SGD",
            "open_time": "05:00-02:00",
            "suggested_duration_hours": 3,
            "preferred_start_time": "18:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/a/a7/Gardens_by_the_Bay_Supertree_Grove_2019.jpg",
        },
        {
            "name": "Marina Bay Sands SkyPark",
            "location": "Marina Bay, Singapore",
            "information": "高空观景平台，适合看滨海湾夜景。",
            "price": 35.00,
            "currency": "SGD",
            "open_time": "11:00-21:00",
            "suggested_duration_hours": 2,
            "preferred_start_time": "19:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/e/e6/Marina_Bay_Sands_in_the_evening_-_20101120.jpg",
        },
        {
            "name": "Merlion Park",
            "location": "Downtown Core, Singapore",
            "information": "新加坡鱼尾狮地标，适合与滨海湾一并游览。",
            "price": 0.00,
            "currency": "SGD",
            "open_time": "00:00-23:59",
            "suggested_duration_hours": 1,
            "preferred_start_time": "08:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/0/0f/Merlion_Park%2C_Singapore_-_20110224.jpg",
        },
        {
            "name": "Singapore Botanic Gardens",
            "location": "Tanglin, Singapore",
            "information": "世界遗产植物园，适合轻松散步。",
            "price": 0.00,
            "currency": "SGD",
            "open_time": "05:00-00:00",
            "suggested_duration_hours": 2,
            "preferred_start_time": "09:00",
            "image": "https://upload.wikimedia.org/wikipedia/commons/1/13/Singapore_Botanic_Gardens_ECO_lake.jpg",
        },
    ],
}


FALLBACK_ATTRACTION = {
    "name": "City Landmark Tour",
    "location": "Central District",
    "information": "经典城市地标，轻松游览",
    "price": 300.00,
    "currency": "MYR",
    "open_time": "09:00-17:00",
    "suggested_duration_hours": 2,
    "preferred_start_time": "10:00",
    "image": "https://upload.wikimedia.org/wikipedia/commons/a/ac/No_image_available.svg",
}

_PLANNER_EXCHANGE_RATES = {
    "MYR": 1.0,
    "RM": 1.0,
    "THB": 0.13,
}


def _load_geopy_modules():
    geopy_spec = find_spec("geopy")
    if geopy_spec is None:
        return None, None

    try:
        geocoders_module = import_module("geopy.geocoders")
        distance_module = import_module("geopy.distance")
    except Exception:
        return None, None

    return getattr(geocoders_module, "Nominatim", None), getattr(distance_module, "geodesic", None)


def _parse_json_query(query: str) -> dict:
    if isinstance(query, dict):
        return query

    text = str(query or "").strip()
    if not text:
        return {}

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}

    return payload if isinstance(payload, dict) else {}


def _safe_parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _normalize_city_key(city: str) -> str:
    return str(city or "").strip().lower()


def _trip_dates(start_date: date, end_date: date) -> list[date]:
    day_count = (end_date - start_date).days + 1
    return [start_date + timedelta(days=offset) for offset in range(max(day_count, 0))]


def _parse_hour_minute(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", 1)
    return int(hour_text), int(minute_text)


def _combine_datetime(day: date, hour_text: str) -> datetime:
    hour, minute = _parse_hour_minute(hour_text)
    return datetime.combine(day, time(hour=hour, minute=minute))


def _format_duration(hours: int) -> str:
    return f"{hours} hour" if hours == 1 else f"{hours} hours"


def _convert_planner_price_to_myr(price: float, currency: str) -> float:
    rate = _PLANNER_EXCHANGE_RATES.get(str(currency or "").upper(), 1.0)
    return float(f"{float(price) * rate:.2f}")


def _build_view(day: date, attraction: dict) -> dict:
    open_start, open_end = attraction["open_time"].split("-", 1)
    arrival_time = _combine_datetime(day, attraction["preferred_start_time"])
    open_start_time = _combine_datetime(day, open_start)
    open_end_time = _combine_datetime(day, open_end)

    if arrival_time < open_start_time:
        arrival_time = open_start_time

    duration_hours = int(attraction["suggested_duration_hours"])
    departure_time = arrival_time + timedelta(hours=duration_hours)
    if departure_time > open_end_time:
        departure_time = open_end_time
        adjusted_hours = max(1, int((departure_time - arrival_time).total_seconds() // 3600))
        duration_hours = adjusted_hours
        arrival_time = departure_time - timedelta(hours=duration_hours)
        if arrival_time < open_start_time:
            arrival_time = open_start_time
            departure_time = min(arrival_time + timedelta(hours=duration_hours), open_end_time)

    duration_hours = max(1, int((departure_time - arrival_time).total_seconds() // 3600) or duration_hours)
    converted_price = _convert_planner_price_to_myr(attraction["price"], attraction.get("currency", "MYR"))

    return {
        "name": attraction["name"],
        "location": attraction["location"],
        "information": attraction["information"],
        "price": converted_price,
        "open_time": attraction["open_time"],
        "arrival_time": arrival_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "departure_time": departure_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "visit_duration": _format_duration(duration_hours),
        "image": attraction["image"],
    }


def _attractions_for_city(city: str) -> list[dict]:
    catalog = TRAVEL_ATTRACTION_CATALOG.get(_normalize_city_key(city), [])
    if catalog:
        return [dict(item) for item in catalog]

    fallback = dict(FALLBACK_ATTRACTION)
    fallback["name"] = f"{city} City Landmark Tour" if city else fallback["name"]
    fallback["location"] = f"Central District, {city}" if city else fallback["location"]
    return [fallback]


def _build_structured_travel_plan(query: str) -> dict:
    payload = _parse_json_query(query)
    cities = [str(city).strip() for city in payload.get("cities", []) if str(city).strip()]
    start_date = _safe_parse_date(payload.get("start_date"))
    end_date = _safe_parse_date(payload.get("end_date"))

    if not cities or not start_date or not end_date or end_date < start_date:
        return {"views": []}

    trip_days = _trip_dates(start_date, end_date)
    if not trip_days:
        return {"views": []}

    city_sequences: list[str] = []
    if len(cities) >= len(trip_days):
        city_sequences = cities[: len(trip_days)]
    else:
        base_days = len(trip_days) // len(cities)
        extra_days = len(trip_days) % len(cities)
        for index, city in enumerate(cities):
            assigned_days = base_days + (1 if index < extra_days else 0)
            city_sequences.extend([city] * assigned_days)

    views: list[dict] = []
    city_offsets: dict[str, int] = {}
    for day, city in zip(trip_days, city_sequences):
        attractions = _attractions_for_city(city)
        planned_count = min(2, len(attractions))
        start_index = city_offsets.get(city, 0)
        selected_attractions: list[dict] = []
        for offset in range(planned_count):
            attraction_index = (start_index + offset) % len(attractions)
            selected_attractions.append(attractions[attraction_index])
        city_offsets[city] = start_index + planned_count
        selected_attractions.sort(key=lambda item: item["preferred_start_time"])
        for attraction in selected_attractions:
            views.append(_build_view(day, attraction))

    return {"views": views}


@tool
def get_location_info(place: str) -> str:
    """
    地图 API 工具：获取地点的详细地址与经纬度坐标
    - 输入：地名（如 "Tokyo Tower" 或 "东京塔"）
    - 输出：详细地址、纬度、经度
    """
    nominatim_cls, _ = _load_geopy_modules()
    if nominatim_cls is None:
        return "地图查询出错：缺少 geopy 依赖，请执行 `pip install -r requirements.txt`。"

    try:
        # 使用 Nominatim（OpenStreetMap）不需要 Key，但需要设置 user_agent
        geolocator = nominatim_cls(user_agent="ai_travel_agent")
        location = geolocator.geocode(place)

        if location:
            return f"地点：{place}\n地址：{location.address}\n坐标：({location.latitude}, {location.longitude})"
        else:
            return f"未找到地点：{place}，请尝试更具体的名称。"
    except Exception as e:
        return f"地图查询出错：{str(e)}"


@tool
def calculate_distance(place_a: str, place_b: str) -> str:
    """
    地图 API 工具：计算两个地点之间的直线距离（公里）
    - 输入：起始地、目的地
    - 输出：距离（km）
    """
    nominatim_cls, geodesic_func = _load_geopy_modules()
    if nominatim_cls is None or geodesic_func is None:
        return "距离计算出错：缺少 geopy 依赖，请执行 `pip install -r requirements.txt`。"

    try:
        geolocator = nominatim_cls(user_agent="ai_travel_agent")
        loc_a = geolocator.geocode(place_a)
        loc_b = geolocator.geocode(place_b)

        if loc_a and loc_b:
            coords_a = (loc_a.latitude, loc_a.longitude)
            coords_b = (loc_b.latitude, loc_b.longitude)
            distance = geodesic_func(coords_a, coords_b).kilometers
            return f"{place_a} 与 {place_b} 的直线距离约为：{distance:.2f} 公里"
        else:
            return "无法找到其中一个地点的坐标，请检查地名。"
    except Exception as e:
        return f"距离计算出错：{str(e)}"


@tool
def travel_planner(query: str) -> str:
    """
    旅行规划工具：根据 JSON 输入生成严格 JSON 行程规划
    - 输入：包含 cities/start_date/end_date/travelers 的 JSON 字符串
    - 输出：{"views":[...]} JSON 字符串
    """
    payload = _parse_json_query(query)
    if {"cities", "start_date", "end_date"}.issubset(payload.keys()):
        return json.dumps(_build_structured_travel_plan(payload), ensure_ascii=False)

    provider = os.getenv("LLM_PROVIDER", "").lower()
    if provider == "google" or os.getenv("GOOGLE_API_KEY"):
        llm = ChatGoogleGenerativeAI(
            model=os.getenv("GOOGLE_LLM_MODEL", "gemini-1.5-flash"),
            api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=0.2,
        )
    else:
        llm = ChatOpenAI(
            model=os.getenv("COMPANY_LLM_MODEL", "gpt-4o-mini"),
            base_url=os.getenv("COMPANY_BASE_URL"),
            api_key=os.getenv("COMPANY_API_KEY"),
            temperature=0.2,
        )

    prompt = f"""
你是一位专业旅行规划师，请根据以下用户需求生成一个简洁易读的旅行方案：
用户需求：{query}

请严格按照以下中文结构输出：
1）行程规划
2）每天安排（按 Day 1/2/3... 列出：上午/下午/晚上）
3）简要预算建议（交通/住宿/餐饮/门票/购物）

要求：
- 结合用户偏好（美食/动漫/文化等）
- 预算给出区间或均值建议，并说明简单理由
"""
    return llm.invoke(prompt).content
