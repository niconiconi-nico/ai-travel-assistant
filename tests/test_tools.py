import json
from datetime import datetime
from pathlib import Path
import sys
import types

TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.append(str(TOOLS_DIR))

import tools


def test_get_location_info_handles_missing_geopy(monkeypatch):
    monkeypatch.setattr(tools, "find_spec", lambda _: None)

    result = tools.get_location_info.invoke({"place": "Tokyo Tower"})

    assert "pip install -r requirements.txt" in result


def test_calculate_distance_handles_missing_geopy(monkeypatch):
    monkeypatch.setattr(tools, "find_spec", lambda _: None)

    result = tools.calculate_distance.invoke({"place_a": "Tokyo Tower", "place_b": "Sensoji"})

    assert "pip install -r requirements.txt" in result


def test_travel_planner_returns_strict_json_for_trip_payload():
    payload = {
        "cities": ["Bangkok", "Pattaya"],
        "start_date": "2026-03-26",
        "end_date": "2026-03-29",
        "travelers": 2,
    }

    result = tools.travel_planner.invoke({"query": json.dumps(payload)})
    parsed = json.loads(result)

    assert list(parsed.keys()) == ["views"]
    assert len(parsed["views"]) == 8
    assert parsed["views"][2]["name"] == "Jim Thompson House Museum"
    assert parsed["views"][4]["name"] == "Sanctuary of Truth"
    assert parsed["views"][6]["name"] == "Pattaya Floating Market"

    first_view = parsed["views"][0]
    assert first_view["name"] == "The Grand Palace"
    assert first_view["location"] == "Phra Nakhon, Bangkok"
    assert first_view["information"] == "泰国皇室地标，建筑华丽"
    assert first_view["price"] == 65.0
    assert first_view["open_time"] == "08:30-15:30"
    assert first_view["visit_duration"] == "3 hours"
    assert first_view["image"].startswith("http")


def test_travel_planner_supports_chinese_city_aliases_with_catalog():
    payload = {
        "cities": ["北京", "上海", "吉隆坡", "槟城"],
        "start_date": "2026-03-26",
        "end_date": "2026-03-29",
        "travelers": 2,
    }

    result = tools.travel_planner.invoke({"query": json.dumps(payload, ensure_ascii=False)})
    parsed = json.loads(result)

    assert parsed["views"][0]["name"] == "The Palace Museum"
    assert parsed["views"][0]["price"] == 39.0
    assert parsed["views"][2]["name"] == "The Bund"
    assert parsed["views"][4]["name"] == "Petronas Twin Towers"
    assert parsed["views"][4]["price"] == 98.0
    assert parsed["views"][6]["name"] == "Penang Hill"
    assert parsed["views"][6]["price"] == 30.0


def test_travel_planner_uses_catalog_for_seoul():
    payload = {
        "cities": ["Seoul"],
        "start_date": "2026-03-26",
        "end_date": "2026-03-27",
        "travelers": 2,
    }

    result = tools.travel_planner.invoke({"query": json.dumps(payload)})
    parsed = json.loads(result)

    assert [view["name"] for view in parsed["views"]] == [
        "Gyeongbokgung Palace",
        "Bukchon Hanok Village",
        "Changdeokgung Palace",
        "N Seoul Tower",
    ]
    assert parsed["views"][0]["price"] == 10.2
    assert all("官方旅遊資訊網站" not in view["name"] for view in parsed["views"])


def test_travel_planner_times_stay_within_trip_dates_and_open_hours():
    payload = {
        "cities": ["Bangkok", "Pattaya"],
        "start_date": "2026-03-26",
        "end_date": "2026-03-29",
        "travelers": 2,
    }

    result = tools.travel_planner.invoke({"query": json.dumps(payload)})
    parsed = json.loads(result)

    for view in parsed["views"]:
        arrival = datetime.fromisoformat(view["arrival_time"])
        departure = datetime.fromisoformat(view["departure_time"])
        open_start, open_end = view["open_time"].split("-", 1)
        start_hour, start_minute = [int(part) for part in open_start.split(":")]
        end_hour, end_minute = [int(part) for part in open_end.split(":")]

        assert arrival.date() >= datetime(2026, 3, 26).date()
        assert departure.date() <= datetime(2026, 3, 29).date()
        assert arrival <= departure
        assert (arrival.hour, arrival.minute) >= (start_hour, start_minute)
        assert (departure.hour, departure.minute) <= (end_hour, end_minute)


def test_travel_planner_returns_fallback_views_for_invalid_payload():
    payload = {"cities": [], "start_date": "bad", "end_date": "2026-03-29"}

    result = tools.travel_planner.invoke({"query": json.dumps(payload)})
    parsed = json.loads(result)

    assert list(parsed.keys()) == ["views"]
    assert len(parsed["views"]) == 1
    assert parsed["views"][0]["name"] == "Trip City City Landmark Tour"
    assert parsed["views"][0]["arrival_time"].startswith("2026-01-01T")
    assert parsed["views"][0]["price"] == 300.0


def test_travel_planner_always_returns_views_for_non_json_input():
    result = tools.travel_planner.invoke({"query": "make me a plan"})
    parsed = json.loads(result)

    assert list(parsed.keys()) == ["views"]
    assert len(parsed["views"]) == 1
    assert parsed["views"][0]["name"] == "Trip City City Landmark Tour"


def test_load_attraction_recommendation_getter_supports_package_import(monkeypatch):
    dummy_module = types.SimpleNamespace(get_attractions_by_place=lambda place, query_type=None: [])

    def fake_import_module(name: str):
        if name == "app.tools.attraction_tool":
            return dummy_module
        raise ImportError(name)

    monkeypatch.setattr(tools, "import_module", fake_import_module)

    getter = tools._load_attraction_recommendation_getter()

    assert getter is dummy_module.get_attractions_by_place


def test_planner_recommendations_load_dotenv_before_lookup(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(tools, "load_dotenv", lambda: calls.append("dotenv"))
    monkeypatch.setattr(tools, "_load_attraction_recommendation_getter", lambda: (lambda place, query_type=None: []))

    tools._planner_attractions_from_recommendations("Seoul")

    assert calls == ["dotenv"]


def test_planner_recommendations_filter_noisy_titles_and_boilerplate(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_load_attraction_recommendation_getter",
        lambda: (
            lambda place, query_type=None: [
                {
                    "name": "景點| 首爾市官方旅遊資訊網站",
                    "brief_description": "景點 | 首爾市官方旅遊資訊網站 跳過導航 Cookie close --> -->",
                    "ticket_price": "",
                },
                {
                    "name": "Gyeongbokgung Palace",
                    "brief_description": "Visit Seoul cookie banner --> -->",
                    "ticket_price": "KRW 3000",
                },
            ]
        ),
    )

    results = tools._planner_attractions_from_recommendations("Seoul")

    assert [item["name"] for item in results] == ["Gyeongbokgung Palace"]
    assert results[0]["information"] == "Gyeongbokgung Palace 是 Seoul 的热门景点。"
    assert results[0]["price"] == 10.2


def test_travel_planner_uses_recommendations_for_non_catalog_city(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_planner_attractions_from_recommendations",
        lambda city: [
            {
                "name": "Gamcheon Culture Village",
                "location": "Saha-gu, Busan",
                "information": "釜山彩色山城聚落，适合步行拍照。",
                "price": 0.0,
                "currency": "KRW",
                "open_time": "09:00-18:00",
                "suggested_duration_hours": 3,
                "preferred_start_time": "09:00",
                "image": "https://example.com/gamcheon.jpg",
            },
            {
                "name": "Haedong Yonggungsa",
                "location": "Gijang-gun, Busan",
                "information": "海边寺庙景观独特。",
                "price": 0.0,
                "currency": "KRW",
                "open_time": "10:00-23:00",
                "suggested_duration_hours": 2,
                "preferred_start_time": "18:00",
                "image": "https://example.com/yonggungsa.jpg",
            },
        ],
    )

    payload = {
        "cities": ["Busan"],
        "start_date": "2026-03-26",
        "end_date": "2026-03-26",
        "travelers": 2,
    }

    result = tools.travel_planner.invoke({"query": json.dumps(payload)})
    parsed = json.loads(result)

    assert [view["name"] for view in parsed["views"]] == ["Gamcheon Culture Village", "Haedong Yonggungsa"]
    assert all("City Landmark Tour" not in view["name"] for view in parsed["views"])
