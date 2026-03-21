from pathlib import Path
import sys

AGENTS_DIR = Path(__file__).resolve().parents[1] / "app" / "agents"
TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "tools"
for path in (AGENTS_DIR, TOOLS_DIR):
    if str(path) not in sys.path:
        sys.path.append(str(path))

import attraction_agent


def test_build_recommendation_from_city_adds_beijing_seeds(monkeypatch):
    monkeypatch.setattr(
        attraction_agent,
        "get_attractions_by_place",
        lambda place, query_type=None: [
            {
                "name": "Beijing Ancient Observatory",
                "brief_description": "Observatory",
                "source_link": "https://example.com/observatory",
            }
        ],
    )

    def fake_get_attraction_info(attraction_name: str, location: str = "", enrichment_mode: str = "detail"):
        return {
            "description": f"{attraction_name} description",
            "image_url": f"https://img.example.com/{attraction_name.replace(' ', '-').lower()}.jpg",
            "ticket_price": "",
            "sources": [f"https://example.com/{attraction_name.replace(' ', '-').lower()}"],
        }

    monkeypatch.setattr(attraction_agent, "get_attraction_info", fake_get_attraction_info)

    result = attraction_agent._build_recommendation_from_city("Beijing", "北京有什么好玩的景点")

    names = [item["name"] for item in result["attractions"]]
    assert "Forbidden City" in names
    assert "Temple of Heaven" in names
    assert "Summer Palace" in names
    assert "Mutianyu Great Wall" in names


def test_normalize_city_maps_kuala_lumpur_chinese_name():
    result = attraction_agent._normalize_city("吉隆坡有什么好玩的景点")

    assert result == "Kuala Lumpur, Malaysia"
