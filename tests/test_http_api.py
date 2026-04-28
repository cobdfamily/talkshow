"""HTTP API tests using FastAPI's TestClient.

Tests all routes via both GET and POST, parameter merging,
error handling, and text combination logic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.plugins import loader
from app.plugins.base import TTSPlugin, SourcePlugin, OutputPlugin


# --- Stub plugins for HTTP tests ---

class FakeTTS(TTSPlugin):
    name = "fake"
    description = "Fake TTS for testing"

    def __init__(self):
        self.last_call = {}

    async def synthesize(self, text, *, voice=None, language=None, rate=None, pitch=None):
        self.last_call = {
            "text": text,
            "voice": voice,
            "language": language,
            "rate": rate,
            "pitch": pitch,
        }
        yield b"RIFF" + b"\x00" * 100  # fake WAV header


class FakeSource(SourcePlugin):
    name = "fakesrc"
    description = "Fake source for testing"

    async def fetch(self, url, *, article_offset=0):
        return {
            "title": f"Article {article_offset}",
            "text": f"Content from {url} at offset {article_offset}",
            "url": url,
            "index": article_offset,
        }

    async def list_articles(self, url):
        return [
            {"title": f"Article {i}", "url": f"{url}/{i}", "index": i}
            for i in range(3)
        ]


class FakeOutput(OutputPlugin):
    name = "fakeout"
    description = "Fake output for testing"
    content_type = "text/plain"

    async def render(
        self, articles, *,
        tts_base_url="", voice=None, language=None, mode="full",
    ):
        titles = ", ".join(a["title"] for a in articles)
        return f"Articles: {titles}"


@pytest.fixture(autouse=True)
def setup_fake_plugins():
    """Register fake plugins before each test, clean up after."""
    loader._tts_plugins.clear()
    loader._source_plugins.clear()
    loader._output_plugins.clear()

    loader.register_tts(FakeTTS())
    loader.register_source(FakeSource())
    loader.register_output(FakeOutput())
    yield
    loader._tts_plugins.clear()
    loader._source_plugins.clear()
    loader._output_plugins.clear()


@pytest.fixture
def client():
    from main import app
    return TestClient(app, raise_server_exceptions=False)


# ========== TTS ROUTES ==========

class TestTTSGet:
    def test_get_tts_with_text(self, client):
        resp = client.get("/speak", params={"text": "hello", "engine": "fake"})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"
        assert len(resp.content) > 0

    def test_get_tts_no_text_returns_400(self, client):
        resp = client.get("/speak")
        assert resp.status_code == 400
        assert "No text" in resp.json()["detail"]

    def test_get_tts_bad_engine_returns_404(self, client):
        resp = client.get("/speak", params={"text": "hi", "engine": "nonexistent"})
        assert resp.status_code == 404
        assert "nonexistent" in resp.json()["detail"]

    def test_get_tts_passes_params(self, client):
        resp = client.get("/speak", params={
            "text": "test",
            "voice": "MyVoice",
            "language": "fr-FR",
            "rate": "+10%",
            "pitch": "-5%",
            "engine": "fake",
        })
        assert resp.status_code == 200
        fake = loader.get_tts("fake")
        assert fake.last_call["text"] == "test"
        assert fake.last_call["voice"] == "MyVoice"
        assert fake.last_call["language"] == "fr-FR"
        assert fake.last_call["rate"] == "+10%"
        assert fake.last_call["pitch"] == "-5%"


class TestTTSPost:
    def test_post_tts_query_only(self, client):
        resp = client.post("/speak", params={"text": "hello", "engine": "fake"})
        assert resp.status_code == 200

    def test_post_tts_body_only(self, client):
        resp = client.post("/speak", json={"text": "hello", "engine": "fake"})
        assert resp.status_code == 200
        fake = loader.get_tts("fake")
        assert fake.last_call["text"] == "hello"

    def test_post_tts_combines_query_and_body_text(self, client):
        resp = client.post("/speak", params={"text": "hello", "engine": "fake"}, json={"text": "world"})
        assert resp.status_code == 200
        fake = loader.get_tts("fake")
        assert fake.last_call["text"] == "hello world"

    def test_post_tts_query_text_first(self, client):
        """Query text should come before body text."""
        resp = client.post("/speak", params={"text": "first", "engine": "fake"}, json={"text": "second"})
        assert resp.status_code == 200
        fake = loader.get_tts("fake")
        assert fake.last_call["text"] == "first second"

    def test_post_tts_no_text_returns_400(self, client):
        resp = client.post("/speak")
        assert resp.status_code == 400

    def test_post_tts_body_params_used_when_query_missing(self, client):
        resp = client.post("/speak", json={
            "text": "test",
            "voice": "BodyVoice",
            "language": "de-DE",
            "rate": "+20%",
            "pitch": "-10%",
            "engine": "fake",
        })
        assert resp.status_code == 200
        fake = loader.get_tts("fake")
        assert fake.last_call["voice"] == "BodyVoice"
        assert fake.last_call["language"] == "de-DE"
        assert fake.last_call["rate"] == "+20%"
        assert fake.last_call["pitch"] == "-10%"

    def test_post_tts_query_params_override_body(self, client):
        resp = client.post(
            "/speak",
            params={"text": "t", "voice": "QueryVoice", "engine": "fake"},
            json={"voice": "BodyVoice"},
        )
        assert resp.status_code == 200
        fake = loader.get_tts("fake")
        assert fake.last_call["voice"] == "QueryVoice"


# ========== SOURCE ROUTES ==========

class TestSourceGet:
    def test_get_source_article(self, client):
        resp = client.get("/source", params={
            "name": "fakesrc",
            "url": "https://example.com",
            "articleOffset": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Article 1"
        assert data["index"] == 1

    def test_get_source_default_offset_zero(self, client):
        resp = client.get("/source", params={
            "name": "fakesrc",
            "url": "https://example.com",
        })
        assert resp.status_code == 200
        assert resp.json()["index"] == 0

    def test_get_source_missing_name_returns_400(self, client):
        resp = client.get("/source", params={"url": "https://example.com"})
        assert resp.status_code == 400
        assert "name" in resp.json()["detail"]

    def test_get_source_missing_url_returns_400(self, client):
        resp = client.get("/source", params={"name": "fakesrc"})
        assert resp.status_code == 400
        assert "url" in resp.json()["detail"]

    def test_get_source_unknown_plugin_returns_404(self, client):
        resp = client.get("/source", params={"name": "nope", "url": "https://x.com"})
        assert resp.status_code == 404


class TestSourcePost:
    def test_post_source_query_params(self, client):
        resp = client.post("/source", params={
            "name": "fakesrc",
            "url": "https://example.com",
            "articleOffset": 2,
        })
        assert resp.status_code == 200
        assert resp.json()["index"] == 2

    def test_post_source_body_params(self, client):
        resp = client.post("/source", json={
            "name": "fakesrc",
            "url": "https://example.com",
            "articleOffset": 1,
        })
        assert resp.status_code == 200
        assert resp.json()["index"] == 1

    def test_post_source_query_overrides_body(self, client):
        resp = client.post(
            "/source",
            params={"name": "fakesrc", "url": "https://query.com"},
            json={"name": "other", "url": "https://body.com"},
        )
        assert resp.status_code == 200
        assert "query.com" in resp.json()["text"]


class TestSourceListGet:
    def test_get_source_list(self, client):
        resp = client.get("/source/list", params={
            "name": "fakesrc",
            "url": "https://example.com",
        })
        assert resp.status_code == 200
        articles = resp.json()
        assert len(articles) == 3

    def test_get_source_list_missing_params(self, client):
        resp = client.get("/source/list")
        assert resp.status_code == 400


class TestSourceListPost:
    def test_post_source_list_body(self, client):
        resp = client.post("/source/list", json={
            "name": "fakesrc",
            "url": "https://example.com",
        })
        assert resp.status_code == 200
        assert len(resp.json()) == 3


# ========== OUTPUT ROUTES ==========

class TestOutputGet:
    def test_get_output(self, client):
        resp = client.get("/output/fakeout", params={
            "source_name": "fakesrc",
            "source_url": "https://example.com",
        })
        assert resp.status_code == 200
        assert "Articles:" in resp.text

    def test_get_output_missing_source_returns_400(self, client):
        resp = client.get("/output/fakeout")
        assert resp.status_code == 400

    def test_get_output_unknown_format_returns_404(self, client):
        resp = client.get("/output/nope", params={
            "source_name": "fakesrc",
            "source_url": "https://example.com",
        })
        assert resp.status_code == 404


class TestOutputPost:
    def test_post_output_query(self, client):
        resp = client.post("/output/fakeout", params={
            "source_name": "fakesrc",
            "source_url": "https://example.com",
        })
        assert resp.status_code == 200
        assert "Articles:" in resp.text

    def test_post_output_body(self, client):
        resp = client.post("/output/fakeout", json={
            "source_name": "fakesrc",
            "source_url": "https://example.com",
        })
        assert resp.status_code == 200
        assert "Articles:" in resp.text

    def test_post_output_query_overrides_body(self, client):
        resp = client.post(
            "/output/fakeout",
            params={"source_name": "fakesrc", "source_url": "https://query.com"},
            json={"source_name": "other", "source_url": "https://body.com"},
        )
        assert resp.status_code == 200


# ========== PLUGIN LISTING ROUTES ==========

class TestPluginRoutes:
    def test_list_all_plugins(self, client):
        resp = client.get("/plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert "tts" in data
        assert "sources" in data
        assert "outputs" in data

    def test_list_plugins_by_type(self, client):
        resp = client.get("/plugins/tts")
        assert resp.status_code == 200
        data = resp.json()
        assert "tts" in data

    def test_list_plugins_invalid_type(self, client):
        resp = client.get("/plugins/bogus")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ========== HEALTH ==========

class TestHealth:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "talkshow"
        assert data["status"] == "ok"
