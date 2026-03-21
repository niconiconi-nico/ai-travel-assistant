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

    result = attraction_agent._build_recommendation_from_city("Beijing", "北京有什么好玩的景点")

    names = [item["name"] for item in result["attractions"]]
    assert "Forbidden City" in names
    assert "Temple of Heaven" in names
    assert "Summer Palace" in names
    assert "Mutianyu Great Wall" in names


def test_normalize_city_maps_kuala_lumpur_chinese_name():
    result = attraction_agent._normalize_city("吉隆坡有什么好玩的景点")

    assert result == "Kuala Lumpur, Malaysia"


def test_build_recommendation_from_city_enriches_thin_candidates_with_detail(monkeypatch):
    monkeypatch.setattr(
        attraction_agent,
        "get_attractions_by_place",
        lambda place, query_type=None: [
            {
                "name": "Petronas Twin Towers",
                "brief_description": "Iconic skyline landmark in Kuala Lumpur.",
                "source_link": "https://example.com/petronas",
            }
        ],
    )

    monkeypatch.setattr(
        attraction_agent,
        "get_attraction_info",
        lambda attraction_name, location=None: {
            "name": attraction_name,
            "description": "Observation deck and skyline icon.",
            "image_url": "https://img.example.com/petronas.jpg",
            "ticket_price": "RM 98",
            "sources": ["https://example.com/detail"],
        },
    )

    result = attraction_agent._build_recommendation_from_city("Kuala Lumpur, Malaysia", "吉隆坡有什么好玩的景点")

    assert result["attractions"] == [
        {
            "name": "Petronas Twin Towers",
            "description": "Iconic skyline landmark in Kuala Lumpur.",
            "image": "https://img.example.com/petronas.jpg",
            "ticket_price": "RM 98",
        }
    ]
    assert result["sources"] == ["https://example.com/petronas"]

def test_normalize_info_preserves_ticket_status_and_price_note():
    normalized = attraction_agent._normalize_info(
        {
            "name": "Petronas Twin Towers",
            "description": "Landmark in Kuala Lumpur.",
            "image_url": "https://img.example.com/petronas.jpg",
            "opening_hours": "",
            "visit_duration": "1-2 hours",
            "ticket_price": "",
            "ticket_status": "partially_paid",
            "price_note": "Exterior visit is free; skybridge admission may require a ticket.",
            "sources": ["https://www.petronastwintowers.com.my/"],
        }
    )

    assert normalized["ticket_status"] == "partially_paid"
    assert "skybridge" in normalized["price_note"].lower()
