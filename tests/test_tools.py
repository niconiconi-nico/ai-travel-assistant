import json
from datetime import datetime
from pathlib import Path
import sys

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
    assert first_view["price"] == 500.0
    assert first_view["open_time"] == "08:30-15:30"
    assert first_view["visit_duration"] == "3 hours"
    assert first_view["image"].startswith("http")


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
