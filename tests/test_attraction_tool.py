from pathlib import Path
import sys

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.append(str(TOOLS_DIR))

import attraction_tool


@pytest.fixture(autouse=True)
def _stub_recommendation_page_fetch(monkeypatch):
    monkeypatch.setattr(attraction_tool, "_fetch_url_text", lambda url, timeout=10: "")


def test_get_attraction_info_without_api_key_returns_safe_defaults(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    result = attraction_tool.get_attraction_info("Tokyo Tower", "Tokyo")

    assert result["name"] == "Tokyo Tower"
    assert result["image_url"] == ""
    assert result["ticket_price"] == ""
    assert "estimated" in result["visit_duration"]
    assert isinstance(result["sources"], list)


def test_get_attraction_info_extracts_core_fields(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {
                "hours": "Open: 9:00 AM - 6:00 PM",
                "description": "Ticket price RM 80 for adults",
            },
            "answer_box": {"answer": "Recommended time: 2 hours"},
            "organic_results": [
                {
                    "title": "Official Site",
                    "link": "https://example.com/official",
                    "snippet": "Opening hours 9:00 AM - 6:00 PM",
                    "thumbnail": "https://img.example.com/thumb.jpg",
                },
                {
                    "title": "TripAdvisor Demo Attraction",
                    "link": "https://tripadvisor.com/demo",
                    "snippet": "Admission fee RM 80",
                },
                {
                    "title": "Klook Demo Attraction",
                    "link": "https://klook.com/demo",
                    "snippet": "How long to spend: 2 hours",
                },
            ],
        }

    def fake_google_images(query: str, api_key: str, num: int = 10):
        return {
            "images_results": [
                {
                    "title": "Spot Image",
                    "original": "https://img.example.com/original.jpg",
                    "thumbnail": "https://img.example.com/tn.jpg",
                    "link": "https://example.com/image",
                }
            ]
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", fake_google_images)
    cache_path = Path("/tmp/attraction_tool_test_cache.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Demo Attraction", "Kuala Lumpur")

    assert result["image_url"].startswith("http")
    assert result["opening_hours"] != ""
    assert result["visit_duration"] != ""
    assert "RM" in result["ticket_price"]
    assert len(result["sources"]) >= 3


def test_get_attractions_by_place(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "organic_results": [
                {
                    "title": "Tokyo Tower - Official Travel Guide",
                    "link": "https://example.com/tokyo-tower",
                    "snippet": "An iconic observation tower in Tokyo.",
                },
                {
                    "title": "Senso-ji Temple | Visit Tokyo",
                    "link": "https://example.com/sensoji",
                    "snippet": "Historic temple in Asakusa district.",
                },
                {
                    "title": "Things to do in Tokyo",
                    "link": "https://example.com/things",
                    "snippet": "Generic page",
                },
            ]
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)

    results = attraction_tool.get_attractions_by_place("Tokyo")

    assert len(results) >= 2
    assert all("name" in item and "brief_description" in item and "source_link" in item for item in results)


def test_normalize_recommendations_with_gemini_reorders_and_sanitizes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")

    class DummyResp:
        content = '{"attractions":[{"name":"A Museum","description":"A curated museum stop.","image":"https://img/a.jpg","ticket_price":"RM 20"},{"name":"B Park","description":"Green urban park.","image":"https://img/should-not-pass.jpg","ticket_price":"RM 999"}]}'

    class DummyLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, _prompt: str):
            return DummyResp()

    monkeypatch.setattr(attraction_tool, "ChatGoogleGenerativeAI", DummyLLM)
    candidates = [
        {
            "name": "A Museum",
            "description": "Museum description",
            "image": "https://img/a.jpg",
            "ticket_price": "RM 20",
            "sources": ["https://example.com/a"],
        },
        {
            "name": "B Park",
            "description": "Park description",
            "image": "",
            "ticket_price": "",
            "sources": ["https://example.com/b"],
        },
    ]

    normalized = attraction_tool.normalize_recommendations_with_gemini(
        user_query="Top attractions in City",
        city="City",
        candidates=candidates,
    )

    assert normalized[0]["name"] == "A Museum"
    assert normalized[0]["image"] == "https://img/a.jpg"
    assert normalized[1]["name"] == "B Park"
    assert normalized[1]["image"] == ""
    assert normalized[1]["ticket_price"] == ""


def test_normalize_recommendations_with_gemini_drops_placeholder_descriptions(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")

    class DummyResp:
        content = '{"attractions":[{"name":"A Temple","description":"A popular temple attraction.","image":"","ticket_price":""}]}'

    class DummyLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, _prompt: str):
            return DummyResp()

    monkeypatch.setattr(attraction_tool, "ChatGoogleGenerativeAI", DummyLLM)
    candidates = [
        {
            "name": "A Temple",
            "description": "Historic waterfront temple.",
            "image": "",
            "ticket_price": "",
            "sources": ["https://example.com/a"],
        },
    ]

    normalized = attraction_tool.normalize_recommendations_with_gemini(
        user_query="Temple recommendations",
        city="City",
        candidates=candidates,
    )

    assert normalized[0]["description"] == "Historic waterfront temple."


def test_get_attractions_by_place_uses_gemini_normalized_order(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    monkeypatch.setattr(
        attraction_tool,
        "_get_osm_city_pois",
        lambda place, limit=14: [
            {"name": "Raw One", "description": "Popular attraction in this destination.", "image": "", "ticket_price": "", "sources": []},
            {"name": "Raw Two", "description": "Good spot", "image": "", "ticket_price": "", "sources": []},
        ],
    )
    monkeypatch.setattr(attraction_tool, "_enrich_poi_with_knowledge", lambda poi, location=None: poi)
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: [
            {
                "name": "Raw Two",
                "description": "Curated description",
                "image": "",
                "ticket_price": "",
                "sources": ["https://example.com/raw-two"],
            },
            {
                "name": "Raw One",
                "description": "Popular attraction in this destination.",
                "image": "",
                "ticket_price": "",
                "sources": ["https://example.com/raw-one"],
            },
        ],
    )

    result = attraction_tool.get_attractions_by_place("City")

    assert result[0]["name"] == "Raw Two"
    assert result[0]["brief_description"] == "Curated description"
    assert result[1]["brief_description"] == ""


def test_opening_hours_and_ticket_price_cleaning(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Example Source",
                    "link": "https://example.com/page?ved=bad",
                    "snippet": "MoNGmgGgNBrE4DSTdHNqXnzAMMG9g3Q3ibqgFu1_c-&q=foo open Tuesday to Sunday, 9am to 9pm",
                },
                {
                    "title": "Official Site",
                    "link": "https://example.com/official",
                    "snippet": "Ticket info rM7; admission starts from RM 127",
                },
                {
                    "title": "TripAdvisor Demo",
                    "link": "https://tripadvisor.com/demo",
                    "snippet": "Great place",
                },
            ],
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})
    cache_path = Path("/tmp/attraction_tool_test_cache_v2.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Demo Tower", "Demo City")

    assert "?q=" not in result["opening_hours"]
    assert "ved=" not in result["opening_hours"]
    assert result["opening_hours"] == "" or "9am to 9pm" in result["opening_hours"].lower()
    assert result["ticket_price"] != "rM7"
    assert "RM" in result["ticket_price"] or "Estimated" in result["ticket_price"]


def test_ticket_price_normalized_to_myr(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Trip Source",
                    "link": "https://trip.com/demo",
                    "snippet": "Admission fee USD 15",
                },
                {
                    "title": "Guide",
                    "link": "https://example.com/guide",
                    "snippet": "Price range ¥40-¥60",
                },
                {
                    "title": "Official",
                    "link": "https://example.com",
                    "snippet": "Open Monday to Sunday 9:00 AM - 6:00 PM",
                },
            ],
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})
    cache_path = Path("/tmp/attraction_tool_test_cache_v3.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Demo Museum", "Kuala Lumpur")

    assert result["ticket_price"].startswith("RM")


def test_invalid_rm7_should_fallback(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Random",
                    "link": "https://example.com",
                    "snippet": "ticket price rM7 only",
                },
                {
                    "title": "Wiki",
                    "link": "https://wikipedia.org/demo",
                    "snippet": "Good place",
                },
                {
                    "title": "TripAdvisor",
                    "link": "https://tripadvisor.com/demo",
                    "snippet": "Nice",
                },
            ],
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", Path("/tmp/attraction_tool_test_cache_v4.json"))

    result = attraction_tool.get_attraction_info("Demo Tower", "KL")

    assert result["ticket_price"] != "rM7"
    assert result["ticket_price"].startswith("RM") or result["ticket_price"] in {"Free", ""}


def test_invalid_cached_entry_should_be_recomputed(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Official Site",
                    "link": "https://example.com/official",
                    "snippet": "April to October, 8:30-17:00",
                },
                {
                    "title": "TripAdvisor",
                    "link": "https://tripadvisor.com/demo",
                    "snippet": "Admission fee USD 15",
                },
                {
                    "title": "Guide",
                    "link": "https://example.com/guide",
                    "snippet": "Closed on Mondays",
                },
            ],
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})

    cache_path = Path("/tmp/attraction_tool_test_cache_invalid.json")
    cache_path.write_text(
        '{"the palace museum::beijing": {"name": "The Palace Museum", "image_url": "", "opening_hours": "bad-token-&q=abc&sa=X", "visit_duration": "3 hours", "ticket_price": "rM7", "sources": []}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("The Palace Museum", "Beijing")

    assert "?q=" not in result["opening_hours"]
    assert "&sa=" not in result["opening_hours"]
    assert result["ticket_price"] != "rM7"
    assert result["ticket_price"].startswith("RM") or result["ticket_price"] == "Free"


def test_resolve_ticket_price_from_sources_prefers_page_content(monkeypatch):
    sources = [
        {
            "title": "Official Tickets",
            "link": "https://example.com/tickets",
            "snippet": "Admission details",
        }
    ]

    monkeypatch.setattr(
        attraction_tool,
        "_fetch_url_text",
        lambda url, timeout=10: "General admission RM 30. Child RM 15.",
    )

    result = attraction_tool.resolve_ticket_price_from_sources(sources)

    assert result == "RM 15–RM 30"


def test_build_ticket_price_candidate_pool_scores_admission_above_parking_and_tour(monkeypatch):
    sources = [
        {
            "title": "Official ticket page",
            "link": "https://official.example.com/tickets",
            "snippet": "Adult admission RM 35. Child admission RM 20.",
        },
        {
            "title": "Visitor info",
            "link": "https://official.example.com/info",
            "snippet": "Parking fee RM 8 near the attraction.",
        },
        {
            "title": "OTA package",
            "link": "https://klook.example.com/demo",
            "snippet": "Full day tour package RM 120 including transfer.",
        },
    ]

    monkeypatch.setattr(
        attraction_tool,
        "_fetch_url_text",
        lambda url, timeout=10: {
            "https://official.example.com/tickets": "Adult admission RM 35. Child admission RM 20.",
            "https://official.example.com/info": "Parking fee RM 8.",
            "https://klook.example.com/demo": "Full day tour package RM 120 including transfer.",
        }.get(url, ""),
    )

    candidates = attraction_tool.build_ticket_price_candidate_pool(
        sources,
        attraction_name="Demo Attraction",
    )

    assert candidates
    assert candidates[0]["raw_price_text"] == "RM 35"
    assert candidates[0]["score"] > candidates[-1]["score"]
    assert "admission" in candidates[0]["context"].lower()


def test_resolve_ticket_price_from_sources_rejects_uncertain_phrases(monkeypatch):
    sources = [
        {
            "title": "Official FAQ",
            "link": "https://example.com/faq",
            "snippet": "ticket info",
        }
    ]

    monkeypatch.setattr(
        attraction_tool,
        "_fetch_url_text",
        lambda url, timeout=10: "Ticket prices start from RM 20 and prices vary by package.",
    )

    result = attraction_tool.resolve_ticket_price_from_sources(sources)

    assert result == ""


def test_resolve_ticket_price_ignores_sub_attraction_context(monkeypatch):
    sources = [
        {
            "title": "Penang Hill Tickets",
            "link": "https://example.com/penang-hill-tickets",
            "snippet": "official admission",
        }
    ]

    monkeypatch.setattr(
        attraction_tool,
        "_fetch_url_text",
        lambda url, timeout=10: "The Habitat Penang Hill package RM 98. Add-on canopy walk RM 60.",
    )

    result = attraction_tool.resolve_ticket_price_from_sources(sources, attraction_name="Penang Hill")

    assert result == ""


def test_price_like_line_should_not_be_opening_hours(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Aquaria KLCC Admission E-Ticket",
                    "link": "https://example.com/aquaria-ticket",
                    "snippet": "Malaysia: Aquaria KLCC Admission E-Ticket · 1 to 2 hours · $17.47",
                },
                {
                    "title": "Official Site",
                    "link": "https://example.com/official",
                    "snippet": "Visit info",
                },
                {
                    "title": "FAQ",
                    "link": "https://example.com/faq",
                    "snippet": "Ticket details",
                },
            ],
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})
    monkeypatch.setattr(attraction_tool, "_fetch_url_text", lambda url, timeout=10: "Malaysia: Aquaria KLCC Admission E-Ticket · 1 to 2 hours · $17.47")
    cache_path = Path("/tmp/attraction_tool_test_cache_price_opening.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Aquaria KLCC", "Kuala Lumpur")

    assert "Admission" not in result["opening_hours"]
    assert "$" not in result["opening_hours"]
    assert result["ticket_price"].startswith("RM")


def test_opening_hours_requires_labeled_or_time_range_format():
    assert attraction_tool.is_valid_opening_hours("Open Daily: 10:00 AM - 8:00 PM")
    assert attraction_tool.is_valid_opening_hours("09:00-18:00")
    assert attraction_tool.is_valid_opening_hours("Tuesday to Sunday, 9:00 AM - 6:00 PM")
    assert not attraction_tool.is_valid_opening_hours("Visit duration 1 to 2 hours")
    assert not attraction_tool.is_valid_opening_hours("00 AM - 9:00")
    assert not attraction_tool.is_valid_opening_hours("30 AM–4:30")
    assert not attraction_tool.is_valid_opening_hours("Open Daily 78 Armenian Street | Georgetown | 10am ~ 10pm")
    assert not attraction_tool.is_valid_opening_hours('Monday", "hours": "8:30 AM–4:30')
    assert not attraction_tool.is_valid_opening_hours("Malaysia: Aquaria KLCC Admission E-Ticket · 1 to 2 hours · $17.47")


def test_clean_opening_hours_extracts_range_from_labeled_jsonish_line():
    raw = 'Opening hours: Monday", "hours": "8:30 AM–4:30 PM", "note":"closed tuesday"'
    assert attraction_tool.clean_opening_hours(raw) == "8:30 AM–4:30 PM"


def test_opening_hours_rejects_zero_text_review_sources(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "TripAdvisor Review",
                    "link": "https://tripadvisor.com/attraction_review-demo",
                    "snippet": "Open Daily 78 Armenian Street | Georgetown | 10am ~ 10pm",
                },
                {
                    "title": "Official Site",
                    "link": "https://example.gov/official",
                    "snippet": "Visitor information",
                },
            ],
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})
    monkeypatch.setattr(attraction_tool, "_fetch_url_text", lambda url, timeout=10: "")
    cache_path = Path("/tmp/attraction_tool_test_cache_hours_source_gate.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Demo Attraction", "City")

    assert result["opening_hours"] == ""


def test_parse_gemini_ticket_payload_handles_markdown_json():
    raw = """```json
{"ticket_price":"$17.47","price_type":"third_party","price_note":"ota page"}
```"""

    parsed = attraction_tool._parse_gemini_ticket_payload(raw)

    assert parsed["ticket_price"].startswith("RM")
    assert parsed["price_type"] == "third_party"


def test_get_attraction_info_prefers_gemini_ticket_resolution(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Official Tickets",
                    "link": "https://example.com/tickets",
                    "snippet": "Admission details",
                },
                {
                    "title": "Official FAQ",
                    "link": "https://example.com/faq",
                    "snippet": "Ticket info",
                },
                {
                    "title": "Official Site",
                    "link": "https://example.com",
                    "snippet": "Visitor info",
                },
            ],
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})
    monkeypatch.setattr(attraction_tool, "_fetch_url_text", lambda url, timeout=10: "Adult admission RM 30")
    monkeypatch.setattr(
        attraction_tool,
        "resolve_ticket_price_with_gemini",
        lambda attraction_name, location, sources, rule_based_price="", aliases=None: {
            "ticket_price": "RM 30",
            "price_type": "official",
            "price_note": "resolved by gemini",
        },
    )
    cache_path = Path("/tmp/attraction_tool_test_cache_gemini.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Demo Attraction", "KL")

    assert result["ticket_price"] == "RM 30"
    assert result["price_type"] == "official"


def test_gemini_ticket_resolution_uses_official_homepage_when_no_ticket_keyword(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    sources = [
        {
            "title": "Official Website",
            "link": "https://example.com/official-home",
            "snippet": "Visit info and contact",
        }
    ]

    class DummyResp:
        content = '{"ticket_price":"RM 25","price_type":"official","price_note":"main admission"}'

    class DummyLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, _prompt: str):
            return DummyResp()

    monkeypatch.setattr(attraction_tool, "ChatGoogleGenerativeAI", DummyLLM)
    monkeypatch.setattr(attraction_tool, "_fetch_url_text", lambda url, timeout=10: "Official admission RM 25 for adults")

    parsed = attraction_tool.resolve_ticket_price_with_gemini("Demo", "City", sources)

    assert parsed["ticket_price"] == "RM 25"
    assert parsed["price_type"] == "official"


def test_recommendation_mode_skips_ticket_enrichment_for_weak_sources(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Official Homepage",
                    "link": "https://example.com/official-home",
                    "snippet": "Visitor information and history",
                },
                {
                    "title": "Wikipedia",
                    "link": "https://en.wikipedia.org/wiki/Demo",
                    "snippet": "General description",
                },
            ],
        }

    called = {"gemini": 0}

    def fake_gemini(*args, **kwargs):
        called["gemini"] += 1
        return {"ticket_price": "RM 30", "price_type": "official", "price_note": "x"}

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})
    monkeypatch.setattr(attraction_tool, "resolve_ticket_price_with_gemini", fake_gemini)
    cache_path = Path("/tmp/attraction_tool_test_cache_reco_skip_price.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Demo Attraction", "City", enrichment_mode="recommendation")

    assert result["ticket_price"] == ""
    assert called["gemini"] == 0


def test_recommendation_mode_attempts_ticket_enrichment_for_strong_sources(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Official Tickets",
                    "link": "https://example.com/tickets",
                    "snippet": "Admission rates",
                }
            ],
        }

    called = {"gemini": 0}

    def fake_gemini(*args, **kwargs):
        called["gemini"] += 1
        return {"ticket_price": "RM 30", "price_type": "official", "price_note": "x"}

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})
    monkeypatch.setattr(attraction_tool, "resolve_ticket_price_with_gemini", fake_gemini)
    monkeypatch.setattr(attraction_tool, "_fetch_url_text", lambda url, timeout=10: "Adult admission RM 30")
    cache_path = Path("/tmp/attraction_tool_test_cache_reco_attempt_price.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Demo Attraction", "City", enrichment_mode="recommendation")

    assert result["ticket_price"] == "RM 30"


def test_get_attraction_info_exposes_ticket_price_candidate_pool(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.setattr(attraction_tool, "_search_osm_poi_by_name", lambda *args, **kwargs: {})
    monkeypatch.setattr(attraction_tool, "fetch_wikipedia_summary", lambda *args, **kwargs: {"description": "", "image_url": "", "source_url": ""})
    monkeypatch.setattr(attraction_tool, "fetch_nominatim_place", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        attraction_tool,
        "_search_google",
        lambda query, api_key, num=10: {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Demo Attraction Official Ticket Page",
                    "link": "https://official.example.com/tickets",
                    "snippet": "Adult admission RM 35. Child admission RM 20.",
                }
            ],
        },
    )
    monkeypatch.setattr(
        attraction_tool,
        "_fetch_url_text",
        lambda url, timeout=10: "Adult admission RM 35. Child admission RM 20.",
    )
    monkeypatch.setattr(
        attraction_tool,
        "resolve_ticket_price_with_gemini",
        lambda *args, **kwargs: {"ticket_price": "", "price_type": "unknown", "price_note": ""},
    )
    cache_path = Path("/tmp/attraction_tool_test_cache_candidate_pool.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Demo Attraction", "City")

    assert result["ticket_price_candidates"]
    assert result["ticket_price_candidates"][0]["raw_price_text"] == "RM 35"



def test_debug_logging_disabled_by_default(monkeypatch, capsys):
    monkeypatch.delenv("ATTRACTION_TOOL_DEBUG", raising=False)

    attraction_tool._debug_log("hidden-message")

    captured = capsys.readouterr()
    assert captured.out == ""


def test_debug_logging_goes_to_stderr_when_enabled(monkeypatch, capsys):
    monkeypatch.setenv("ATTRACTION_TOOL_DEBUG", "true")

    attraction_tool._debug_log("visible-message")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "visible-message" in captured.err



def test_get_attractions_by_place_filters_generic_titles(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.setattr(attraction_tool, "_get_osm_city_pois", lambda place, limit=14: [])
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: candidates,
    )

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "organic_results": [
                {
                    "title": "Discover the 11 most beautiful sights & attractions in Beijing",
                    "link": "https://example.com/discover-beijing",
                    "snippet": "Generic list article.",
                },
                {
                    "title": "Temple of Heaven Park - Beijing Travel",
                    "link": "https://example.com/temple-of-heaven",
                    "snippet": "Historic imperial complex in Beijing.",
                },
            ]
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)

    result = attraction_tool.get_attractions_by_place("Beijing")

    assert result[0]["name"] == "Temple of Heaven Park"
    assert all(item["name"] != "Discover the 11 most beautiful sights & attractions in Beijing" for item in result)


def test_get_attractions_by_place_filters_generic_destination_guides_and_city_pages(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.setattr(attraction_tool, "_get_osm_city_pois", lambda place, limit=8: [])
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: candidates,
    )

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "organic_results": [
                {
                    "title": "THE 10 BEST Pattaya Sights & Historical Landmarks ...",
                    "link": "https://tripadvisor.com/pattaya-list",
                    "snippet": "3. Big Buddha Temple · 4. Pattaya Floating Market · 5. Beach Road",
                },
                {
                    "title": "芭堤雅旅游指南｜幕后建议、隐藏瑰宝、行程规划等",
                    "link": "https://klook.com/pattaya-guide",
                    "snippet": "热门行程和城市玩法总览",
                },
                {
                    "title": "Pattaya",
                    "link": "https://tourismthailand.org/pattaya",
                    "snippet": "City overview page",
                },
                {
                    "title": "Sanctuary of Truth",
                    "link": "https://example.com/sanctuary",
                    "snippet": "All-wood sanctuary in Pattaya.",
                },
                {
                    "title": "Pattaya Floating Market",
                    "link": "https://example.com/floating-market",
                    "snippet": "Popular cultural market in Pattaya.",
                },
            ]
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)

    result = attraction_tool.get_attractions_by_place("Pattaya")

    top_names = [item["name"] for item in result[:3]]
    assert "Sanctuary of Truth" in top_names
    assert "Pattaya Floating Market" in top_names
    assert all(item["name"] not in {"Pattaya", "THE 10 BEST Pattaya Sights & Historical Landmarks ..."} for item in result)


def test_get_attractions_by_place_filters_noisy_chinese_guide_and_tour_titles(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.setattr(attraction_tool, "_get_osm_city_pois", lambda place, limit=8: [])
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: candidates,
    )

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "organic_results": [
                {
                    "title": "芭堤雅必玩熱門旅遊景點與一日遊行程及門票",
                    "link": "https://example.com/pattaya-guide",
                    "snippet": "熱門景點 · 喬木提恩海灘 · 芭堤雅海灘 · 步行街",
                },
                {
                    "title": "Pattaya Landmark Tours",
                    "link": "https://example.com/pattaya-tours",
                    "snippet": "Explore Pattaya on a full-day tour with a guide.",
                },
                {
                    "title": "【2025芭堤雅自由行】一篇搞定！芭堤雅景點美食、交通",
                    "link": "https://example.com/pattaya-free-travel",
                    "snippet": "含17個景點如真理寺、七珍佛山",
                },
                {
                    "title": "EP5-",
                    "link": "https://youtube.com/demo",
                    "snippet": "泰国芭提雅2026超强攻略",
                },
                {
                    "title": "The Sanctuary of Truth",
                    "link": "https://example.com/sanctuary",
                    "snippet": "All-wood sanctuary in Pattaya.",
                },
                {
                    "title": "Dolphinarium Pattaya",
                    "link": "https://example.com/dolphinarium",
                    "snippet": "Popular dolphin show venue in Pattaya.",
                },
            ]
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)

    result = attraction_tool.get_attractions_by_place("Pattaya")

    names = [item["name"] for item in result]
    assert "The Sanctuary of Truth" in names
    assert "Dolphinarium Pattaya" in names
    assert "芭堤雅必玩熱門旅遊景點與一日遊行程及門票" not in names
    assert "Pattaya Landmark Tours" not in names
    assert "【2025芭堤雅自由行】一篇搞定！芭堤雅景點美食、交通" not in names
    assert "EP5-" not in names


def test_get_osm_city_pois_does_not_query_place_of_worship(monkeypatch):
    captured = {"query": ""}

    monkeypatch.setattr(
        attraction_tool,
        "_resolve_place_geometry",
        lambda place: {"lat": 3.139, "lon": 101.687, "south": 3.0, "north": 3.2},
    )

    def fake_overpass(query: str):
        captured["query"] = query
        return {"elements": []}

    monkeypatch.setattr(attraction_tool, "_run_overpass_query", fake_overpass)

    attraction_tool._get_osm_city_pois("Kuala Lumpur", limit=5)

    assert "place_of_worship" not in captured["query"]


def test_get_attractions_by_place_queries_serpapi_before_osm_only_lists(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.setattr(
        attraction_tool,
        "_get_osm_city_pois",
        lambda place, limit=8: [
            {
                "name": f"Local Park {idx}",
                "description": "",
                "image": "",
                "ticket_price": "",
                "sources": [f"https://osm.example.com/{idx}"],
            }
            for idx in range(1, 9)
        ],
    )
    monkeypatch.setattr(attraction_tool, "_enrich_poi_with_knowledge", lambda poi, location=None: poi)
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: candidates,
    )

    queries: list[str] = []

    def fake_google_search(query: str, api_key: str, num: int = 10):
        queries.append(query)
        return {
            "organic_results": [
                {
                    "title": "Petronas Twin Towers - Official Guide",
                    "link": "https://example.com/petronas",
                    "snippet": "Iconic skyline landmark in Kuala Lumpur.",
                }
            ]
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)

    result = attraction_tool.get_attractions_by_place("Kuala Lumpur")

    assert queries
    assert result[0]["name"] == "Petronas Twin Towers"


def test_get_attractions_by_place_uses_gemini_to_extract_entities_from_list_articles(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setattr(attraction_tool, "_get_osm_city_pois", lambda place, limit=8: [])
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: candidates,
    )

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "organic_results": [
                {
                    "title": "THE 10 BEST Kuala Lumpur Sights & Landmarks",
                    "link": "https://example.com/kl-list",
                    "snippet": "Petronas Twin Towers, KL Tower, Batu Caves and Central Market are must-visit stops.",
                }
            ]
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(
        attraction_tool,
        "_extract_search_candidates_with_gemini",
        lambda place, query, organic_results: [
            {
                "name": "Petronas Twin Towers",
                "description": "Iconic twin-tower landmark in central Kuala Lumpur.",
                "image": "",
                "ticket_price": "",
                "sources": ["https://example.com/kl-list"],
                "source_type": "serpapi",
            },
            {
                "name": "KL Tower",
                "description": "Observation tower with city views.",
                "image": "",
                "ticket_price": "",
                "sources": ["https://example.com/kl-list"],
                "source_type": "serpapi",
            },
        ],
    )

    result = attraction_tool.get_attractions_by_place("Kuala Lumpur")

    assert [item["name"] for item in result[:2]] == ["Petronas Twin Towers", "KL Tower"]
    assert all("BEST Kuala Lumpur" not in item["name"] for item in result)


def test_extract_search_candidates_with_gemini_rejects_ungrounded_name_and_cleans_mixed_script(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")

    class DummyResponse:
        content = '{"attractions":[{"name":"真理寺The Sanctuary of Truth","description":"A popular temple attraction.","source_index":0},{"name":"天坛大佛","description":"A popular attraction.","source_index":0}]}'

    class DummyLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, prompt):
            return DummyResponse()

    monkeypatch.setattr(attraction_tool, "ChatGoogleGenerativeAI", DummyLLM)

    results = attraction_tool._extract_search_candidates_with_gemini(
        place="Pattaya",
        query="芭提雅有什么好玩的景点",
        organic_results=[
            {
                "title": "Best Places To Visit in Pattaya",
                "snippet": "Top attractions in Pattaya include The Sanctuary of Truth and Pattaya Floating Market.",
                "link": "https://example.com/pattaya-list",
            }
        ],
    )

    assert results == [
        {
            "name": "The Sanctuary of Truth",
            "description": "Top attractions in Pattaya include The Sanctuary of Truth and Pattaya Floating Market.",
            "image": "",
            "ticket_price": "",
            "sources": ["https://example.com/pattaya-list"],
            "page_text": "",
            "source_type": "search_entity",
            "source_title": "Best Places To Visit in Pattaya",
            "source_snippet": "Top attractions in Pattaya include The Sanctuary of Truth and Pattaya Floating Market.",
        }
    ]


def test_extract_search_candidates_with_gemini_uses_page_text_for_grounding_and_description(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    captured_prompt = {}

    class DummyResponse:
        content = '{"attractions":[{"name":"Pattaya Floating Market","description":"","source_index":0}]}'

    class DummyLLM:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, prompt):
            captured_prompt["value"] = prompt
            return DummyResponse()

    monkeypatch.setattr(attraction_tool, "ChatGoogleGenerativeAI", DummyLLM)
    monkeypatch.setattr(
        attraction_tool,
        "_fetch_url_text",
        lambda url, timeout=10: (
            "Plan your visit to Pattaya. Pattaya Floating Market is a waterfront market featuring canals "
            "and Thai cultural performances. Opening hours and tickets are listed on this page."
        ),
    )

    results = attraction_tool._extract_search_candidates_with_gemini(
        place="Pattaya",
        query="Pattaya attractions",
        organic_results=[
            {
                "title": "Things to do in Pattaya",
                "snippet": "Visitor guide overview.",
                "link": "https://example.com/pattaya-guide",
            }
        ],
    )

    assert "page_text" in captured_prompt["value"]
    assert "pattaya floating market is a waterfront market featuring canals and thai cultural performances" in captured_prompt["value"].lower()
    assert results == [
        {
            "name": "Pattaya Floating Market",
            "description": "Pattaya Floating Market is a waterfront market featuring canals and Thai cultural performances",
            "image": "",
            "ticket_price": "",
            "sources": ["https://example.com/pattaya-guide"],
            "page_text": "Plan your visit to Pattaya. Pattaya Floating Market is a waterfront market featuring canals and Thai cultural performances. Opening hours and tickets are listed on this page.",
            "source_type": "search_entity",
            "source_title": "Things to do in Pattaya",
            "source_snippet": "Visitor guide overview.",
        }
    ]


def test_get_attractions_by_place_fallback_prefers_page_text_description(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(attraction_tool, "_get_osm_city_pois", lambda place, limit=8: [])
    monkeypatch.setattr(
        attraction_tool,
        "_search_google",
        lambda query, api_key, num=10: {
            "organic_results": [
                {
                    "title": "Sanctuary of Truth",
                    "link": "https://example.com/sanctuary",
                    "snippet": "Popular attraction.",
                }
            ]
        },
    )
    monkeypatch.setattr(
        attraction_tool,
        "_fetch_url_text",
        lambda url, timeout=10: (
            "The Sanctuary of Truth is an all-wood sanctuary and museum in Pattaya with intricate carved architecture. "
            "Visitors explore exhibition halls and seaside viewpoints."
        ),
    )
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: candidates,
    )

    results = attraction_tool.get_attractions_by_place("Pattaya")

    assert results[0]["name"] == "Sanctuary of Truth"
    assert "all-wood sanctuary and museum in Pattaya" in results[0]["brief_description"]


def test_extract_poi_from_element_rejects_generic_osm_object_without_attraction_signal():
    result = attraction_tool._extract_poi_from_element(
        {
            "type": "node",
            "id": 123,
            "tags": {
                "name": "Airplane",
                "historic": "aircraft",
            },
        }
    )

    assert result == {}


def test_is_valid_recommendation_entity_rejects_article_and_product_candidates():
    article_candidate = {
        "name": "North Pattaya 427 must-visit attractions",
        "description": "City guide roundup.",
        "sources": ["https://example.com/pattaya-guide"],
        "source_type": "serpapi",
        "source_title": "North Pattaya 427 must-visit attractions",
        "source_snippet": "Guide to food, transport and tours.",
    }
    product_candidate = {
        "name": "Pattaya Landmark Tours",
        "description": "Explore Pattaya on a full-day tour.",
        "sources": ["https://example.com/pattaya-tours"],
        "source_type": "serpapi",
        "source_title": "Pattaya Landmark Tours",
        "source_snippet": "Hotel pickup included.",
    }
    valid_candidate = {
        "name": "The Sanctuary of Truth",
        "description": "All-wood sanctuary and museum in Pattaya.",
        "sources": ["https://example.com/sanctuary"],
        "source_type": "search_entity",
        "source_title": "The Sanctuary of Truth",
        "source_snippet": "All-wood sanctuary in Pattaya.",
    }

    assert attraction_tool._is_valid_recommendation_entity(article_candidate, "Pattaya") is False
    assert attraction_tool._is_valid_recommendation_entity(product_candidate, "Pattaya") is False
    assert attraction_tool._is_valid_recommendation_entity(valid_candidate, "Pattaya") is True


def test_get_attractions_by_place_canonicalizes_chinese_city_name(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.setattr(attraction_tool, "_get_osm_city_pois", lambda place, limit=8: [])
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: candidates,
    )

    queries: list[str] = []

    def fake_google_search(query: str, api_key: str, num: int = 10):
        queries.append(query)
        return {"organic_results": []}

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)

    attraction_tool.get_attractions_by_place("吉隆坡")

    assert queries
    assert queries[0].startswith("Kuala Lumpur, Malaysia")


def test_get_attractions_by_place_uses_generic_wikipedia_fallback_when_search_and_osm_are_empty(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setattr(attraction_tool, "_get_osm_city_pois", lambda place, limit=14: [])
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: candidates,
    )
    monkeypatch.setattr(
        attraction_tool,
        "_search_wikipedia_titles",
        lambda query, limit=8: [
            {"title": "Tokyo Tower"},
            {"title": "Sensō-ji"},
            {"title": "Tourism in Tokyo"},
        ],
    )

    def fake_wikipedia_summary(attraction_name: str, location=None):
        summaries = {
            "Tokyo Tower": {
                "description": "Observation tower and major Tokyo landmark.",
                "image_url": "https://img.example.com/tokyo-tower.jpg",
                "source_url": "https://example.com/wiki/tokyo-tower",
            },
            "Sensō-ji": {
                "description": "Historic Buddhist temple in Tokyo.",
                "image_url": "https://img.example.com/sensoji.jpg",
                "source_url": "https://example.com/wiki/sensoji",
            },
        }
        return summaries.get(attraction_name, {"description": "", "image_url": "", "source_url": ""})

    monkeypatch.setattr(attraction_tool, "fetch_wikipedia_summary", fake_wikipedia_summary)

    result = attraction_tool.get_attractions_by_place("Tokyo")

    names = [item["name"] for item in result]
    assert "Tokyo Tower" in names
    assert "Sensō-ji" in names
    tokyo_tower = next(item for item in result if item["name"] == "Tokyo Tower")
    assert tokyo_tower["brief_description"] == "Observation tower and major Tokyo landmark."
    assert all(item["name"] != "Tourism in Tokyo" for item in result)


def test_get_attractions_by_place_uses_offline_catalog_when_external_sources_fail(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setattr(attraction_tool, "_get_osm_city_pois", lambda place, limit=14: [])
    monkeypatch.setattr(attraction_tool, "_search_wikipedia_titles", lambda query, limit=8: [])
    monkeypatch.setattr(
        attraction_tool,
        "normalize_recommendations_with_gemini",
        lambda user_query, city, candidates: candidates,
    )

    result = attraction_tool.get_attractions_by_place("Tokyo")

    assert [item["name"] for item in result[:2]] == ["Tokyo Tower", "Sensō-ji"]
    assert result[0]["brief_description"]


def test_parse_gemini_ticket_payload_converts_cny_to_rm():
    raw = """```json
{"ticket_price":"成人20元/人","price_type":"official","price_note":"gov page"}
```"""

    parsed = attraction_tool._parse_gemini_ticket_payload(raw)

    assert parsed["ticket_price"].startswith("RM")
    assert parsed["price_type"] == "official"


def test_normalize_ticket_price_converts_thb_to_rm():
    normalized = attraction_tool.normalize_ticket_price("THB 500")

    assert normalized == "RM 65"


def test_get_attraction_info_uses_reasonableness_gemini_for_partial_paid_cases(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setattr(attraction_tool, "_search_osm_poi_by_name", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        attraction_tool,
        "fetch_wikipedia_summary",
        lambda attraction_name, location=None: {
            "description": "Iconic twin-tower landmark in Kuala Lumpur.",
            "image_url": "https://img.example.com/petronas.jpg",
            "source_url": "https://example.com/wiki/petronas",
        },
    )
    monkeypatch.setattr(attraction_tool, "fetch_nominatim_place", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        attraction_tool,
        "_search_google",
        lambda query, api_key, num=10: {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Petronas Twin Towers Official Website",
                    "link": "https://www.petronastwintowers.com.my/",
                    "snippet": "Visit the towers and skybridge experience.",
                }
            ],
        },
    )
    monkeypatch.setattr(
        attraction_tool,
        "collect_preferred_sources",
        lambda *args, **kwargs: [
            {
                "title": "Petronas Twin Towers Official Website",
                "link": "https://www.petronastwintowers.com.my/",
                "snippet": "Visit the towers and skybridge experience.",
            }
        ],
    )
    monkeypatch.setattr(attraction_tool, "resolve_ticket_price_from_sources", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        attraction_tool,
        "resolve_ticket_price_with_gemini",
        lambda *args, **kwargs: {"ticket_price": "", "price_type": "unknown", "price_note": ""},
    )
    monkeypatch.setattr(
        attraction_tool,
        "analyze_visit_reasonableness_with_gemini",
        lambda *args, **kwargs: {
            "opening_hours": "",
            "ticket_price": "",
            "ticket_status": "partially_paid",
            "price_note": "Exterior visit is free; skybridge admission may require a ticket.",
        },
    )
    cache_path = Path("/tmp/attraction_tool_test_cache_reasonableness.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Petronas Twin Towers", "Kuala Lumpur")

    assert result["ticket_price"] == ""
    assert result["ticket_status"] == "partially_paid"
    assert "skybridge" in result["price_note"].lower()


def test_get_attraction_info_uses_english_alias_lookup_for_chinese_name(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setattr(attraction_tool, "_search_osm_poi_by_name", lambda *args, **kwargs: {})

    def fake_wikipedia_summary(attraction_name: str, location=None):
        if attraction_name == "petronas twin towers":
            return {
                "description": "Petronas Twin Towers are landmark skyscrapers in Kuala Lumpur.",
                "image_url": "https://img.example.com/petronas.jpg",
                "source_url": "https://example.com/wiki/petronas",
            }
        return {"description": "", "image_url": "", "source_url": ""}

    monkeypatch.setattr(attraction_tool, "fetch_wikipedia_summary", fake_wikipedia_summary)
    monkeypatch.setattr(attraction_tool, "fetch_nominatim_place", lambda *args, **kwargs: {})
    cache_path = Path("/tmp/attraction_tool_test_cache_alias_lookup.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("双子塔", "Kuala Lumpur")

    assert result["name"] == "petronas twin towers"
    assert "landmark skyscrapers" in result["description"].lower()


def test_get_attraction_info_rejects_wrong_attraction_ticket_source(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    monkeypatch.setattr(attraction_tool, "_search_osm_poi_by_name", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        attraction_tool,
        "fetch_wikipedia_summary",
        lambda attraction_name, location=None: {
            "description": "Observatory in Beijing.",
            "image_url": "https://img.example.com/observatory.jpg",
            "source_url": "https://example.com/wiki/observatory",
        },
    )
    monkeypatch.setattr(
        attraction_tool,
        "fetch_nominatim_place",
        lambda attraction_name, location=None: {"display_name": "Beijing Ancient Observatory", "osm_url": ""},
    )

    def fake_google_search(query: str, api_key: str, num: int = 10):
        return {
            "knowledge_graph": {},
            "answer_box": {},
            "organic_results": [
                {
                    "title": "Temple of Heaven - Beijing",
                    "link": "https://english.beijing.gov.cn/specials/parktours/guidevisitors/templeofheaven/",
                    "snippet": "Temple of Heaven admission 10元 to 28元.",
                }
            ],
        }

    monkeypatch.setattr(attraction_tool, "_search_google", fake_google_search)
    monkeypatch.setattr(attraction_tool, "_search_google_images", lambda *args, **kwargs: {"images_results": []})
    monkeypatch.setattr(
        attraction_tool,
        "_fetch_url_text",
        lambda url, timeout=10: "Temple of Heaven ticket prices 10元, 14元, 28元.",
    )
    cache_path = Path("/tmp/attraction_tool_test_cache_wrong_source.json")
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", cache_path)

    result = attraction_tool.get_attraction_info("Beijing Ancient Observatory", "Beijing")

    assert result["ticket_price"] == ""
