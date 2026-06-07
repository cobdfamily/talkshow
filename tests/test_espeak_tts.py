"""Tests for the espeak-ng offline TTS plugin (v1.1.0).

These run the REAL espeak-ng binary when it's on PATH (it is in
CI's runner image and the talkshow container), so synthesis is
verified end to end with no cloud credentials. Synthesis tests
skip gracefully if the binary is absent.
"""

from __future__ import annotations

import shutil

import pytest

from talkshow.plugins.tts.espeak_tts import EspeakTTS

_HAS_ESPEAK = shutil.which(EspeakTTS._BIN) is not None
_needs_espeak = pytest.mark.skipif(
    not _HAS_ESPEAK,
    reason="espeak-ng binary not on PATH",
)


def test_plugin_identity():
    p = EspeakTTS()
    assert p.name == "espeak"
    assert "offline" in p.description.lower()


def test_loader_discovers_espeak():
    """The loader auto-registers any TTSPlugin in tts/; espeak
    must show up alongside azure."""
    from talkshow.plugins import loader

    loader._tts_plugins.clear()
    loader.load_all()
    names = set(loader.list_tts())
    assert "espeak" in names
    assert "azure" in names  # default still present


def test_resolve_cache_path_deterministic(monkeypatch, tmp_path):
    """Same inputs -> same path; the path lives under
    <cache>/espeak/<language>/<voice>/."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()
    a = p.resolve_cache_path("hello", voice="en", language="en")
    b = p.resolve_cache_path("hello", voice="en", language="en")
    assert a == b
    assert a.parent == tmp_path / "espeak" / "en" / "en"
    assert a.suffix == ".wav"
    # Different text -> different file.
    assert p.resolve_cache_path("other", voice="en", language="en") != a


def test_prosody_args_only_for_integer_values():
    p = EspeakTTS()
    assert p._prosody_args("0%", "0%") == []  # default %-shape: no flags
    assert p._prosody_args("150", "40") == ["-s", "150", "-p", "40"]


# ---------------------------------------------------------------------------
# Binary-independent tests. These mock the espeak-ng subprocess so the
# synthesize / _synthesize_to_file / _stream_file paths are exercised
# deterministically whether or not the binary is on PATH (CI runners
# without espeak-ng would otherwise leave these lines uncovered).
# ---------------------------------------------------------------------------


class _FakeProc:
    """Stand-in for the asyncio subprocess from create_subprocess_exec."""

    def __init__(self, returncode: int = 0, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self, _input: bytes | None = None):
        return (b"", self._stderr)


def _patch_exec(monkeypatch, capture: dict, *, returncode: int = 0, stderr: bytes = b""):
    async def fake_exec(*args, **kwargs):
        capture["args"] = args
        capture["kwargs"] = kwargs
        return _FakeProc(returncode=returncode, stderr=stderr)

    monkeypatch.setattr(
        "talkshow.plugins.tts.espeak_tts.asyncio.create_subprocess_exec",
        fake_exec,
    )


def test_resolve_cache_path_ssml_is_distinct(monkeypatch, tmp_path):
    """SSML keys on the markup with placeholder rate/pitch, so it lands
    on a different cache file than the same text rendered plainly."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()
    plain = p.resolve_cache_path("hello", voice="en", language="en")
    ssml = p.resolve_cache_path(
        "hello",
        ssml="<speak>hello</speak>",
        voice="en",
        language="en",
    )
    assert ssml != plain
    assert ssml.parent == tmp_path / "espeak" / "en" / "en"


@pytest.mark.asyncio
async def test_synthesize_cache_miss_then_streams(monkeypatch, tmp_path):
    """On a miss, synthesize() invokes the engine, then streams the
    freshly written cache file back in chunks."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()

    async def fake_to_file(self, text, ssml, voice, rate, pitch, cached):
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(b"RIFFfake-wave-payload")

    monkeypatch.setattr(EspeakTTS, "_synthesize_to_file", fake_to_file)

    chunks = [c async for c in p.synthesize("hello world", voice="en")]
    assert b"".join(chunks) == b"RIFFfake-wave-payload"
    assert p.resolve_cache_path("hello world", voice="en").exists()


@pytest.mark.asyncio
async def test_synthesize_cache_hit_does_not_resynthesize(monkeypatch, tmp_path):
    """A pre-existing cache file is streamed without invoking the engine."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()
    cached = p.resolve_cache_path("cached one", voice="en")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"already-here")

    called = False

    async def boom(self, *args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(EspeakTTS, "_synthesize_to_file", boom)

    out = b"".join([c async for c in p.synthesize("cached one", voice="en")])
    assert out == b"already-here"
    assert called is False


@pytest.mark.asyncio
async def test_stream_file_chunks(monkeypatch, tmp_path):
    """_stream_file yields the file in chunk_size slices."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()
    f = tmp_path / "audio.bin"
    f.write_bytes(b"x" * 20000)  # > 2 chunks at chunk_size=8192
    chunks = [c async for c in p._stream_file(f)]
    assert len(chunks) == 3
    assert b"".join(chunks) == b"x" * 20000


@pytest.mark.asyncio
async def test_synthesize_to_file_success_plain_text(monkeypatch, tmp_path):
    """A clean espeak run (exit 0) renames the temp WAV into place; no
    -m flag is passed for plain text, and -v selects the voice."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()
    capture: dict = {}
    _patch_exec(monkeypatch, capture, returncode=0)
    cached = p.resolve_cache_path("hello", voice="en")
    cached.parent.mkdir(parents=True, exist_ok=True)

    await p._synthesize_to_file("hello", None, "en", "0%", "0%", cached)

    assert cached.exists()
    assert "-m" not in capture["args"]
    assert "-v" in capture["args"]


@pytest.mark.asyncio
async def test_synthesize_to_file_ssml_adds_markup_flag(monkeypatch, tmp_path):
    """SSML input passes espeak-ng's -m markup flag."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()
    capture: dict = {}
    _patch_exec(monkeypatch, capture, returncode=0)
    cached = p.resolve_cache_path("x", ssml="<speak>hi</speak>", voice="en")
    cached.parent.mkdir(parents=True, exist_ok=True)

    await p._synthesize_to_file("ignored", "<speak>hi</speak>", "en", "0%", "0%", cached)

    assert "-m" in capture["args"]
    assert cached.exists()


@pytest.mark.asyncio
async def test_synthesize_to_file_raises_on_nonzero_exit(monkeypatch, tmp_path):
    """A non-zero espeak exit raises and leaves no cache file behind."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()
    capture: dict = {}
    _patch_exec(monkeypatch, capture, returncode=1, stderr=b"bad voice")
    cached = p.resolve_cache_path("hello", voice="en")
    cached.parent.mkdir(parents=True, exist_ok=True)

    with pytest.raises(RuntimeError, match="espeak-ng failed"):
        await p._synthesize_to_file("hello", None, "en", "0%", "0%", cached)
    assert not cached.exists()


@_needs_espeak
@pytest.mark.asyncio
async def test_synthesize_produces_wav_and_caches(monkeypatch, tmp_path):
    """Real espeak-ng run: synthesise produces a RIFF/WAVE file,
    streams non-empty bytes, and writes the cache file."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()
    chunks = [c async for c in p.synthesize("hello world", voice="en")]
    audio = b"".join(chunks)
    assert audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
    cached = p.resolve_cache_path("hello world", voice="en")
    assert cached.exists()
    assert cached.read_bytes() == audio


@_needs_espeak
@pytest.mark.asyncio
async def test_second_call_is_cache_hit(monkeypatch, tmp_path):
    """A second identical request streams the cached file
    unchanged (no re-synthesis clobber)."""
    monkeypatch.setenv("TALKSHOW_CACHE_DIR", str(tmp_path))
    p = EspeakTTS()
    first = b"".join([c async for c in p.synthesize("cache me", voice="en")])
    cached = p.resolve_cache_path("cache me", voice="en")
    mtime_before = cached.stat().st_mtime_ns
    second = b"".join([c async for c in p.synthesize("cache me", voice="en")])
    assert second == first
    # Cache hit path doesn't rewrite the file.
    assert cached.stat().st_mtime_ns == mtime_before
