"""HTTP API tests via FastAPI's TestClient.

Talkshow has a single endpoint: ``/speak``. It accepts content as
SSML (verbatim), plain text, or by fetching a source plugin. These
tests exercise all three input shapes plus the parameter-merging
contract on POST (query takes precedence over body).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from talkshow.plugins import loader
from talkshow.plugins.base import SourcePlugin, TTSPlugin


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

    async def fetch(self, url, *, offset=0, part="body"):
        self.last_call = {"url": url, "offset": offset, "part": part}
        title = f"Article {offset}"
        body = f"Content from {url} at offset {offset}"
        header = f"Header for article {offset}"
        return {
            "title": title,
            "text": header if part == "header" else body,
            "url": url,
            "header": header,
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
    from talkshow.main import app
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# /speak — text input
# ===========================================================================


class TestSpeakText:
    def test_get_with_text(self, client, fake_tts):
        r = client.get("/v1/speak", params={"text": "hello", "engine": "fake"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
        assert fake_tts.last_call["text"] == "hello"
        assert fake_tts.last_call["ssml"] is None

    def test_post_text_in_body(self, client, fake_tts):
        r = client.post(
            "/v1/speak",
            params={"engine": "fake"},
            json={"text": "from body"},
        )
        assert r.status_code == 200
        assert fake_tts.last_call["text"] == "from body"

    def test_post_query_overrides_body(self, client, fake_tts):
        r = client.post(
            "/v1/speak",
            params={"text": "from-query", "engine": "fake"},
            json={"text": "from-body"},
        )
        assert r.status_code == 200
        # query wins
        assert fake_tts.last_call["text"] == "from-query"

    def test_no_input_returns_400(self, client):
        r = client.get("/v1/speak", params={"engine": "fake"})
        assert r.status_code == 400
        assert "ssml" in r.json()["detail"]


# ===========================================================================
# /speak — SSML input
# ===========================================================================


class TestSpeakSSML:
    def test_ssml_passes_through_verbatim(self, client, fake_tts):
        ssml = "<speak><voice name='x'>hi</voice></speak>"
        r = client.get("/v1/speak", params={"ssml": ssml, "engine": "fake"})
        assert r.status_code == 200
        assert fake_tts.last_call["ssml"] == ssml
        # text-shaped path is empty when SSML wins
        assert fake_tts.last_call["text"] == ""

    def test_ssml_takes_precedence_over_text(self, client, fake_tts):
        r = client.get(
            "/v1/speak",
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
            "/v1/speak",
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
            "part": "body",
        }
        # Source returned the body (default); TTS got that text.
        assert "offset 2" in fake_tts.last_call["text"]

    def test_url_with_part_header(self, client, fake_tts, fake_source):
        r = client.get(
            "/v1/speak",
            params={
                "url": "https://example.com",
                "part": "header",
                "engine": "fake",
            },
        )
        assert r.status_code == 200
        assert fake_source.last_call["part"] == "header"
        assert fake_tts.last_call["text"].startswith("Header for article")

    def test_url_unknown_source_returns_404(self, client):
        r = client.get(
            "/v1/speak",
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
        r = client.get("/v1/speak", params={"text": "hi", "engine": "nope"})
        assert r.status_code == 404


# ===========================================================================
# /plugins — discovery
# ===========================================================================


class TestPluginRoutes:
    def test_list_all_plugins(self, client):
        r = client.get("/v1/plugins")
        assert r.status_code == 200
        body = r.json()
        assert "tts" in body
        assert "sources" in body
        # No "outputs" key any more.
        assert "outputs" not in body

    def test_list_plugins_by_type(self, client):
        r = client.get("/v1/plugins/tts")
        assert r.status_code == 200
        assert any(p["name"] == "fake" for p in r.json()["tts"])

    def test_unknown_plugin_type_returns_404(self, client):
        r = client.get("/v1/plugins/outputs")
        assert r.status_code == 404


# ===========================================================================
# / — health endpoint stays
# ===========================================================================


class TestHealth:
    def test_root_health(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["service"] == "talkshow"
