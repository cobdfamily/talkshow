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
