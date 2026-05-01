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
        # /queue tests can stub this with a temp path that does
        # or does not exist, depending on what the test needs.
        self._cache_path_override = None

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
        # Honour the override the same way synthesize would honour
        # a real cache file: if the test pointed us at a file that
        # exists, the synth would have found it first and not needed
        # to do new work — but since we're a fake, just write the
        # bytes the test is asserting on, and also write to the
        # override path so /queue's "ready" check passes after one
        # round-trip.
        if self._cache_path_override is not None:
            self._cache_path_override.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path_override.write_bytes(b"RIFF" + b"\x00" * 100)
        yield b"RIFF" + b"\x00" * 100  # fake WAV header

    def resolve_cache_path(
        self, text, *, ssml=None, voice=None, language=None, rate=None, pitch=None,
    ):
        if self._cache_path_override is not None:
            return self._cache_path_override
        return self.cache_path(
            ssml or text,
            language or "en-US",
            voice or "FakeVoice",
            rate or "0%",
            pitch or "0%",
        )


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
# /queue — cache-warm endpoint
# ===========================================================================


class TestQueue:
    def test_queue_cold_returns_ready_false(self, client, fake_tts, tmp_path):
        # Point the fake at a path that does NOT exist yet.
        fake_tts._cache_path_override = tmp_path / "nope.wav"
        r = client.get("/v1/queue", params={"text": "hi", "engine": "fake"})
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is False
        assert "path" not in body  # only sent when ready

    def test_queue_warm_returns_ready_true_with_path(
        self, client, fake_tts, tmp_path, monkeypatch,
    ):
        # The /speak path-parameter validation requires the file to
        # be inside TALKSHOW_CACHE_DIR; /queue's response uses the
        # absolute path. Point the cache root at tmp_path so the
        # warm file qualifies.
        monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))

        warm = tmp_path / "warm.wav"
        warm.write_bytes(b"RIFF" + b"\x00" * 100)
        fake_tts._cache_path_override = warm

        r = client.get("/v1/queue", params={"text": "hi", "engine": "fake"})
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is True
        assert body["path"] == str(warm.resolve())

    def test_queue_post_with_body(self, client, fake_tts, tmp_path):
        fake_tts._cache_path_override = tmp_path / "post.wav"
        r = client.post(
            "/v1/queue",
            params={"engine": "fake"},
            json={"text": "from-body"},
        )
        assert r.status_code == 200
        assert "ready" in r.json()

    def test_queue_reports_attempts_and_error_after_failure(
        self, client, fake_tts, tmp_path,
    ):
        """When background synthesis fails, /queue must surface
        attempts + error on the next poll."""
        from talkshow.routes import tts as tts_route

        fake_tts._cache_path_override = tmp_path / "broken.wav"
        # Simulate a previous failure recorded by _kickoff_synthesis.
        tts_route._FAILED[fake_tts._cache_path_override] = {
            "attempts": 1,
            "error": "Azure said no",
        }

        try:
            r = client.get(
                "/v1/queue", params={"text": "hi", "engine": "fake"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body == {
                "ready": False,
                "attempts": 1,
                "error": "Azure said no",
            }
        finally:
            tts_route._FAILED.pop(fake_tts._cache_path_override, None)

    def test_queue_stops_retrying_after_max_attempts(
        self, client, fake_tts, tmp_path,
    ):
        """At MAX_QUEUE_ATTEMPTS, /queue must NOT spawn another
        synthesis task; it just reports the failure and stops."""
        from talkshow.routes import tts as tts_route

        fake_tts._cache_path_override = tmp_path / "dead.wav"
        tts_route._FAILED[fake_tts._cache_path_override] = {
            "attempts": tts_route.MAX_QUEUE_ATTEMPTS,
            "error": "permanent",
        }

        try:
            r = client.get(
                "/v1/queue", params={"text": "hi", "engine": "fake"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["ready"] is False
            assert body["attempts"] == tts_route.MAX_QUEUE_ATTEMPTS
            assert body["error"] == "permanent"
        finally:
            tts_route._FAILED.pop(fake_tts._cache_path_override, None)

    def test_queue_no_input_returns_400(self, client):
        r = client.get("/v1/queue", params={"engine": "fake"})
        assert r.status_code == 400

    def test_queue_unknown_engine_returns_404(self, client):
        r = client.get("/v1/queue", params={"text": "hi", "engine": "nope"})
        assert r.status_code == 404


# ===========================================================================
# /cache — stream a previously cached file by absolute path
# ===========================================================================


class TestCache:
    def test_cache_serves_cached_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
        cached = tmp_path / "ready.wav"
        cached.write_bytes(b"RIFF" + b"\x00" * 100)

        r = client.get("/v1/cache", params={"path": str(cached)})
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
        assert r.content.startswith(b"RIFF")

    def test_cache_path_outside_cache_dir_returns_403(
        self, client, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
        outside = tmp_path.parent / "outside.wav"
        outside.write_bytes(b"RIFF" + b"\x00" * 100)
        try:
            r = client.get("/v1/cache", params={"path": str(outside)})
            assert r.status_code == 403
        finally:
            outside.unlink(missing_ok=True)

    def test_cache_path_traversal_returns_403(
        self, client, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
        traversal = str(tmp_path / ".." / "etc" / "passwd")
        r = client.get("/v1/cache", params={"path": traversal})
        assert r.status_code == 403

    def test_cache_missing_file_returns_404(
        self, client, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
        r = client.get(
            "/v1/cache", params={"path": str(tmp_path / "missing.wav")},
        )
        assert r.status_code == 404

    def test_cache_symlink_to_outside_returns_403(
        self, client, tmp_path, monkeypatch,
    ):
        """A symlink that LIVES inside the cache dir but POINTS at a
        file outside it must be rejected — Path.resolve() follows the
        link, so the safety check sees the real (outside) target."""
        monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
        outside = tmp_path.parent / "secret.wav"
        outside.write_bytes(b"RIFF" + b"\x00" * 100)
        link = tmp_path / "evil.wav"
        link.symlink_to(outside)
        try:
            r = client.get("/v1/cache", params={"path": str(link)})
            assert r.status_code == 403
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

    def test_cache_non_wav_extension_returns_403(
        self, client, tmp_path, monkeypatch,
    ):
        """Even when the file is inside the cache dir, the suffix
        check rejects anything that isn't ``.wav``."""
        monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
        bad = tmp_path / "secret.txt"
        bad.write_text("not audio")
        r = client.get("/v1/cache", params={"path": str(bad)})
        assert r.status_code == 403
        assert "wav" in r.json()["detail"].lower()

    def test_cache_partial_write_tmp_file_returns_403(
        self, client, tmp_path, monkeypatch,
    ):
        """The atomic-write window leaves a ``.wav.tmp`` sibling on
        disk during synthesis. The suffix check rejects those so a
        racy /cache call can't serve a half-written file."""
        monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
        partial = tmp_path / "midwrite.wav.tmp"
        partial.write_bytes(b"RIFF" + b"\x00" * 100)
        r = client.get("/v1/cache", params={"path": str(partial)})
        assert r.status_code == 403

    def test_cache_uppercase_wav_extension_allowed(
        self, client, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
        cached = tmp_path / "loud.WAV"
        cached.write_bytes(b"RIFF" + b"\x00" * 100)
        r = client.get("/v1/cache", params={"path": str(cached)})
        assert r.status_code == 200

    def test_cache_path_param_required(self, client):
        r = client.get("/v1/cache")
        assert r.status_code == 422  # FastAPI validation: missing required query


# ===========================================================================
# / — health endpoint stays
# ===========================================================================


class TestHealth:
    def test_root_health(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["service"] == "talkshow"
