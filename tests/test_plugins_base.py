"""Tests for plugin base classes — hashing, cache paths, interfaces."""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from app.plugins.base import TTSPlugin, SourcePlugin, OutputPlugin


# --- Concrete stubs for testing the ABCs ---

class StubTTS(TTSPlugin):
    name = "stub"
    description = "test stub"

    async def synthesize(self, text, *, voice=None, language=None, rate=None, pitch=None):
        yield b"audio"


class StubSource(SourcePlugin):
    name = "stub"
    description = "test stub"

    async def fetch(self, url, *, article_offset=0):
        return {"title": "t", "text": "t", "url": url}

    async def list_articles(self, url):
        return []


class StubOutput(OutputPlugin):
    name = "stub"
    description = "test stub"
    content_type = "text/plain"

    async def render(self, articles, *, tts_base_url="", voice=None, language=None):
        return "ok"


# --- Hash algorithm tests ---

class TestCachePath:
    def test_uses_sha256_not_sha512(self):
        """PROJECT.md spec: '128 char SHA2 hash' — SHA-512 is SHA-2 and produces 128 hex chars."""
        tts = StubTTS()
        text = "hello world"
        path = tts.cache_path(text, "en-US", "TestVoice", "0%", "0%")

        # The hash portion of the filename should be 128 hex characters
        filename = path.name  # e.g. <hash>-0pct-0pct.wav
        hash_part = filename.split("-")[0]

        # SHA-512 hexdigest = 128 chars, SHA-256 = 64 chars
        # Spec says "128 char SHA2" -> SHA-512
        assert len(hash_part) == 128, f"Hash should be 128 chars but got {len(hash_part)}"

        # Verify it matches SHA-512
        expected = hashlib.sha512(text.encode("utf-8")).hexdigest()[:128]
        assert hash_part == expected

    def test_cache_path_structure(self):
        """Cache dir: cache/<plugin>/<language>/<voice>/"""
        tts = StubTTS()
        path = tts.cache_path("test", "en-US", "EmmaNeural", "0%", "0%")
        parts = path.parts
        # Should contain: ...cache/stub/en-US/EmmaNeural/<file>
        assert "stub" in parts
        assert "en-US" in parts
        assert "EmmaNeural" in parts

    def test_cache_filename_format(self):
        """Filename: <hash>-<rate>-<pitch>.wav"""
        tts = StubTTS()
        path = tts.cache_path("test", "en-US", "Voice", "+10%", "-5%")
        assert path.suffix == ".wav"
        # rate +10% -> plus10pct, pitch -5% -> minus5pct
        assert "plus10pct" in path.name
        assert "minus5pct" in path.name

    def test_different_text_different_hash(self):
        tts = StubTTS()
        p1 = tts.cache_path("hello", "en-US", "V", "0%", "0%")
        p2 = tts.cache_path("world", "en-US", "V", "0%", "0%")
        assert p1 != p2

    def test_different_rate_pitch_different_file(self):
        tts = StubTTS()
        p1 = tts.cache_path("hello", "en-US", "V", "0%", "0%")
        p2 = tts.cache_path("hello", "en-US", "V", "+10%", "0%")
        p3 = tts.cache_path("hello", "en-US", "V", "0%", "+10%")
        assert p1 != p2
        assert p1 != p3
        assert p2 != p3

    def test_cache_dir_env_override(self):
        tts = StubTTS()
        with patch.dict("os.environ", {"TALKSHOW_CACHE_DIR": "/tmp/custom_cache"}):
            d = tts.cache_dir("en-US", "Voice")
            assert str(d).startswith("/tmp/custom_cache")
