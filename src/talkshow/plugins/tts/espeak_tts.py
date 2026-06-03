"""espeak-ng TTS plugin -- an offline, no-credentials backend.

Second TTS backend (v1.1.0), demonstrating that the TTSPlugin
ABC takes a non-Azure engine cleanly. Unlike Azure this needs no
subscription key or network: it shells out to the ``espeak-ng``
CLI (the same engine brian uses for its ``<Say>`` renders), so
it's the fleet's no-cloud fallback voice -- useful for air-gapped
dev, CI, and as a degraded-mode voice if the Azure key is absent.

It is NOT the default: Azure's multilingual neural voice stays
the default for production menus (blindhub.ca relies on it). Pick
this engine explicitly with ``?engine=espeak``.

Requires the ``espeak-ng`` binary on PATH (added to the talkshow
image in v1.1.0).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncIterator

from ..base import TTSPlugin


class EspeakTTS(TTSPlugin):
    name = "espeak"
    description = "espeak-ng offline (no-credentials) Text-to-Speech"

    # The binary is overridable for tests / unusual installs.
    _BIN = os.getenv("TALKSHOW_ESPEAK_BIN", "espeak-ng")

    def _get_default(self, key: str, fallback: str) -> str:
        return os.getenv(f"ESPEAK_DEFAULT_{key.upper()}", fallback)

    def _resolve_defaults(
        self,
        voice: str | None,
        language: str | None,
        rate: str | None,
        pitch: str | None,
    ) -> tuple[str, str, str, str]:
        # espeak's voice name doubles as its language selector
        # (e.g. "en", "en-us", "fr"); language is kept only for
        # cache-path layout so a voice+language pair caches
        # distinctly.
        return (
            voice or self._get_default("voice", "en"),
            language or self._get_default("language", "en"),
            rate or self._get_default("rate", "0%"),
            pitch or self._get_default("pitch", "0%"),
        )

    def resolve_cache_path(
        self,
        text: str,
        *,
        ssml: str | None = None,
        voice: str | None = None,
        language: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> Path:
        voice, language, rate, pitch = self._resolve_defaults(
            voice,
            language,
            rate,
            pitch,
        )
        if ssml:
            # SSML carries its own prosody; key on the markup plus
            # voice/language, placeholder rate/pitch (mirrors Azure).
            return self.cache_path(ssml, language, voice, "ssml", "ssml")
        return self.cache_path(text, language, voice, rate, pitch)

    def _prosody_args(self, rate: str, pitch: str) -> list[str]:
        """Map the interface's rate/pitch onto espeak CLI flags.

        The interface passes Azure-shaped percentage strings
        ("0%"). espeak wants words-per-minute (-s) and a 0-99
        pitch (-p). We only pass a flag when the value parses as a
        plain integer (an operator opting into espeak-native
        tuning); the default "0%" is left to espeak's own defaults
        but still distinguishes the cache key.
        """
        args: list[str] = []
        if rate.lstrip("+-").isdigit():
            args += ["-s", rate.lstrip("+")]
        if pitch.lstrip("+-").isdigit():
            args += ["-p", pitch.lstrip("+")]
        return args

    async def synthesize(
        self,
        text: str,
        *,
        ssml: str | None = None,
        voice: str | None = None,
        language: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> AsyncIterator[bytes]:
        voice, language, rate, pitch = self._resolve_defaults(
            voice,
            language,
            rate,
            pitch,
        )
        cached = self.resolve_cache_path(
            text,
            ssml=ssml,
            voice=voice,
            language=language,
            rate=rate,
            pitch=pitch,
        )

        if cached.exists():
            async for chunk in self._stream_file(cached):
                yield chunk
            return

        cached.parent.mkdir(parents=True, exist_ok=True)
        await self._synthesize_to_file(text, ssml, voice, rate, pitch, cached)

        async for chunk in self._stream_file(cached):
            yield chunk

    async def _synthesize_to_file(
        self,
        text: str,
        ssml: str | None,
        voice: str,
        rate: str,
        pitch: str,
        cached: Path,
    ) -> None:
        """Run espeak-ng, writing a WAV to a short-named temp
        file in the cache dir then atomically renaming into place
        (so a concurrent ``cached.exists()`` reader never sees a
        half-written file -- same contract as the Azure plugin).

        Why a short temp name rather than ``<cached>.tmp``:
        espeak-ng silently writes NOTHING (exit 0, no file) when
        its ``-w`` path exceeds an internal ~242-char buffer, and
        our cache filename is a 128-char hash -- under a deep
        cache root that tips over. So espeak writes to a short
        mkstemp name; the rename to the long final path is
        Python's os.replace, which has no such limit.
        """
        fd, tmp_name = tempfile.mkstemp(dir=str(cached.parent), suffix=".wav")
        os.close(fd)
        tmp_path = Path(tmp_name)
        args = [self._BIN, "-v", voice, *self._prosody_args(rate, pitch)]
        # espeak-ng's -m enables its (subset) SSML markup parser.
        payload = ssml if ssml else text
        if ssml:
            args.append("-m")
        # -w writes a WAV; text comes on stdin so long/odd input
        # can't collide with argv parsing.
        args += ["-w", str(tmp_path)]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(payload.encode("utf-8"))
        if proc.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"espeak-ng failed (exit {proc.returncode}): "
                f"{stderr.decode('utf-8', 'replace')[:200]}"
            )
        tmp_path.replace(cached)

    async def _stream_file(self, path: Path, chunk_size: int = 8192) -> AsyncIterator[bytes]:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, path.read_bytes)
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]
