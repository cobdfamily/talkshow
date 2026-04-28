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

    Source plugins fetch one article from a URL. The contract is
    deliberately small — three knobs and an article dict back:

      url      The URL to fetch from. May point at a single article
               or at an index page that lists multiple.
      offset   When the URL is an index, the zero-based index of
               which article to fetch.
      summary  ``True`` returns the article's summary (title + a
               short description). ``False`` returns the full body.

    The plugin decides for itself whether ``url`` is an index or a
    single-article URL — call sites don't need to know.

    Implementations return a dict with at minimum:

      title, text, url

    Plus an optional ``summary`` key that callers may render as the
    short form. When ``summary`` is True, the ``text`` field SHOULD
    contain the summary so dumb consumers still work.
    """

    name: str  # e.g. "wordpress"
    description: str

    @abstractmethod
    async def fetch(
        self,
        url: str,
        *,
        offset: int = 0,
        summary: bool = False,
    ) -> dict:
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
        article: dict,
        *,
        tts_base_url: str = "",
        voice: str | None = None,
        language: str | None = None,
    ) -> str:
        """Render a single article into the output format.

        Args:
            article: Article dict returned by a SourcePlugin's
                ``fetch(...)``. Includes ``title``, ``text``,
                ``url``. Whether ``text`` is full body or summary
                is decided upstream by the source's ``summary``
                argument; the output plugin renders whatever it's
                given.
            tts_base_url: Base URL for TTS audio endpoints.
            voice: Voice to use for TTS references.
            language: Language to use for TTS references.

        Returns:
            Formatted string (e.g. XML).
        """
        ...
