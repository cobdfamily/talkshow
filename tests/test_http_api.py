"""HTTP API tests via FastAPI's TestClient.

Talkshow has a single endpoint: ``/speak``. It accepts content as
SSML (verbatim), plain text, or by fetching a source plugin. These
tests exercise all three input shapes plus the parameter-merging
contract on POST (query takes precedence over body).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.plugins import loader
from app.plugins.base import SourcePlugin, TTSPlugin


# --- Stub plugins for HTTP tests ---

class FakeTTS(TTSPlugin):
    name = "fake"
    description = "Fake TTS for testing"

    def __init__(self):
        self.last_call = {}

    async def synthesize(
        self, text, *,
        ssml=None, voice=None, language=None, rate=None, pitch=None,
    ):
        self.last_call = {
            "text": text,
            "ssml": ssml,
            "voice": voice,
            "language": language,
            "rate": rate,
            "pitch": pitch,
        }
        yield b"RIFF" + b"\x00" * 100  # fake WAV header


class FakeSource(SourcePlugin):
    name = "wordpress"  # so default source resolution finds it
    description = "Fake source for testing"

    def __init__(self):
        self.last_call = {}

    async def fetch(self, url, *, offset=0, summary=False):
        self.last_call = {"url": url, "offset": offset, "summary": summary}
        title = f"Article {offset}"
        body = f"Content from {url} at offset {offset}"
        excerpt = f"Summary of article {offset}"
        return {
            "title": title,
            "text": excerpt if summary else body,
            "url": url,
            "summary": excerpt,
            "offset": offset,
        }


@pytest.fixture
def fake_tts():
    return FakeTTS()


@pytest.fixture
def fake_source():
    return FakeSource()


@pytest.fixture(autouse=True)
def setup_fake_plugins(fake_tts, fake_source):
    """Register fake plugins before each test, clean up after."""
    loader._tts_plugins.clear()
    loader._source_plugins.clear()
    loader.register_tts(fake_tts)
    loader.register_source(fake_source)
    yield
    loader._tts_plugins.clear()
    loader._source_plugins.clear()


@pytest.fixture
def client():
    from main import app
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# /speak — text input
# ===========================================================================


class TestSpeakText:
    def test_get_with_text(self, client, fake_tts):
        r = client.get("/speak", params={"text": "hello", "engine": "fake"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
        assert fake_tts.last_call["text"] == "hello"
        assert fake_tts.last_call["ssml"] is None

    def test_post_text_in_body(self, client, fake_tts):
        r = client.post(
            "/speak",
            params={"engine": "fake"},
            json={"text": "from body"},
        )
        assert r.status_code == 200
        assert fake_tts.last_call["text"] == "from body"

    def test_post_query_overrides_body(self, client, fake_tts):
        r = client.post(
            "/speak",
            params={"text": "from-query", "engine": "fake"},
            json={"text": "from-body"},
        )
        assert r.status_code == 200
        # query wins
        assert fake_tts.last_call["text"] == "from-query"

    def test_no_input_returns_400(self, client):
        r = client.get("/speak", params={"engine": "fake"})
        assert r.status_code == 400
        assert "ssml" in r.json()["detail"]


# ===========================================================================
# /speak — SSML input
# ===========================================================================


class TestSpeakSSML:
    def test_ssml_passes_through_verbatim(self, client, fake_tts):
        ssml = "<speak><voice name='x'>hi</voice></speak>"
        r = client.get("/speak", params={"ssml": ssml, "engine": "fake"})
        assert r.status_code == 200
        assert fake_tts.last_call["ssml"] == ssml
        # text-shaped path is empty when SSML wins
        assert fake_tts.last_call["text"] == ""

    def test_ssml_takes_precedence_over_text(self, client, fake_tts):
        r = client.get(
            "/speak",
            params={"ssml": "<speak>x</speak>", "text": "ignored", "engine": "fake"},
        )
        assert r.status_code == 200
        assert fake_tts.last_call["ssml"] == "<speak>x</speak>"
        assert fake_tts.last_call["text"] == ""


# ===========================================================================
# /speak — URL input (source fetch)
# ===========================================================================


class TestSpeakURL:
    def test_url_fetches_via_source_plugin(self, client, fake_tts, fake_source):
        r = client.get(
            "/speak",
            params={
                "url": "https://example.com",
                "offset": 2,
                "engine": "fake",
            },
        )
        assert r.status_code == 200
        assert fake_source.last_call == {
            "url": "https://example.com",
            "offset": 2,
            "summary": False,
        }
        # Source returned the body (full mode); TTS got that text.
        assert "offset 2" in fake_tts.last_call["text"]

    def test_url_with_summary_true(self, client, fake_tts, fake_source):
        r = client.get(
            "/speak",
            params={
                "url": "https://example.com",
                "summary": "true",
                "engine": "fake",
            },
        )
        assert r.status_code == 200
        assert fake_source.last_call["summary"] is True
        assert fake_tts.last_call["text"].startswith("Summary of article")

    def test_url_unknown_source_returns_404(self, client):
        r = client.get(
            "/speak",
            params={
                "url": "https://example.com",
                "source": "nope",
                "engine": "fake",
            },
        )
        assert r.status_code == 404


# ===========================================================================
# /speak — engine selection
# ===========================================================================


class TestSpeakEngine:
    def test_unknown_engine_returns_404(self, client):
        r = client.get("/speak", params={"text": "hi", "engine": "nope"})
        assert r.status_code == 404


# ===========================================================================
# /plugins — discovery
# ===========================================================================


class TestPluginRoutes:
    def test_list_all_plugins(self, client):
        r = client.get("/plugins")
        assert r.status_code == 200
        body = r.json()
        assert "tts" in body
        assert "sources" in body
        # No "outputs" key any more.
        assert "outputs" not in body

    def test_list_plugins_by_type(self, client):
        r = client.get("/plugins/tts")
        assert r.status_code == 200
        assert any(p["name"] == "fake" for p in r.json()["tts"])

    def test_unknown_plugin_type_returns_404(self, client):
        r = client.get("/plugins/outputs")
        assert r.status_code == 404


# ===========================================================================
# / — health endpoint stays
# ===========================================================================


class TestHealth:
    def test_root_health(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["service"] == "talkshow"
