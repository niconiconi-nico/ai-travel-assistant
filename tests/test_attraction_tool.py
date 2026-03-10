from pathlib import Path
import sys

TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.append(str(TOOLS_DIR))

import attraction_tool


def test_get_attraction_info_without_api_key_returns_safe_defaults(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    result = attraction_tool.get_attraction_info("Tokyo Tower", "Tokyo")

    assert result["name"] == "Tokyo Tower"
    assert result["image_url"] == ""
    assert result["ticket_price"] != ""
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
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", Path("/tmp/attraction_tool_test_cache.json"))

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
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", Path("/tmp/attraction_tool_test_cache_v2.json"))

    result = attraction_tool.get_attraction_info("Demo Tower", "Demo City")

    assert "?q=" not in result["opening_hours"]
    assert "ved=" not in result["opening_hours"]
    assert "9am to 9pm" in result["opening_hours"].lower()
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
    monkeypatch.setattr(attraction_tool, "_CACHE_PATH", Path("/tmp/attraction_tool_test_cache_v3.json"))

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
    assert result["ticket_price"].startswith("RM") or result["ticket_price"] == "Free"


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
