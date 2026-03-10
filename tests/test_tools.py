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
