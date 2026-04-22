"""Abstract base classes for all plugin types.

Third-party plugins implement these interfaces and place their module
in the corresponding plugin directory (tts/, sources/, outputs/).
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import AsyncIterator


class TTSPlugin(ABC):
    """Base class for text-to-speech engine plugins.

    Subclasses handle speech synthesis, file caching, and streaming.
    All caching logic lives here (not in core) so plugins are reusable.
    """

    name: str  # e.g. "azure"
    description: str

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> AsyncIterator[bytes]:
        """Synthesize text to speech and yield audio chunks.

        Implementations should:
        1. Check cache via `cache_path()` — if the file exists, stream it.
        2. Otherwise, synthesize, write the file, and stream.
        """
        ...

    def cache_dir(self, language: str, voice: str) -> Path:
        """Return the cache directory for a given language/voice combo."""
        base = Path(os.getenv("TALKSHOW_CACHE_DIR", "cache"))
        return base / self.name / language / voice

    def cache_path(
        self, text: str, language: str, voice: str, rate: str, pitch: str
    ) -> Path:
        """Return the full cache file path for a synthesis request.

        Filename: 128-char SHA-2 (SHA-512) hex digest of the text + -<rate>-<pitch>.wav
        """
        text_hash = hashlib.sha512(text.encode("utf-8")).hexdigest()[:128]
        safe_rate = rate.replace("%", "pct").replace("+", "plus").replace("-", "minus")
        safe_pitch = pitch.replace("%", "pct").replace("+", "plus").replace("-", "minus")
        filename = f"{text_hash}-{safe_rate}-{safe_pitch}.wav"
        return self.cache_dir(language, voice) / filename


class SourcePlugin(ABC):
    """Base class for data source plugins.

    Source plugins fetch content from URLs (e.g. WordPress tags, Hugo tags).
    """

    name: str  # e.g. "wordpress"
    description: str

    @abstractmethod
    async def fetch(
        self,
        url: str,
        *,
        article_offset: int = 0,
    ) -> dict:
        """Fetch content from the given URL.

        Returns a dict with at least:
            - "title": article title
            - "text": article body text
            - "url": canonical URL
        """
        ...

    @abstractmethod
    async def list_articles(self, url: str) -> list[dict]:
        """List available articles from the source URL.

        Returns a list of dicts with at least:
            - "title": article title
            - "url": article URL
            - "index": position in the list
        """
        ...


class OutputPlugin(ABC):
    """Base class for output formatter plugins.

    Output plugins produce non-audio responses, such as Twilio XML / Signalwire LAML
    for phone system navigation.
    """

    name: str  # e.g. "twilio_xml"
    description: str
    content_type: str  # e.g. "application/xml"

    @abstractmethod
    async def render(
        self,
        articles: list[dict],
        *,
        tts_base_url: str = "",
        voice: str | None = None,
        language: str | None = None,
        mode: str = "full",
    ) -> str:
        """Render the given articles into the output format.

        Args:
            articles: List of article dicts from a SourcePlugin.
            tts_base_url: Base URL for TTS audio endpoints.
            voice: Voice to use for TTS references.
            language: Language to use for TTS references.
            mode: "full" (include body), "summary" (header only),
                  or "nextArticle" (header of next article).

        Returns:
            Formatted string (e.g. XML).
        """
        ...
