"""Microsoft Azure TTS plugin.

Uses the Azure Cognitive Services Speech SDK for synthesis.
Handles caching and streaming per the plugin interface contract.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator
from xml.sax.saxutils import escape as xml_escape

import azure.cognitiveservices.speech as speechsdk

from ..base import TTSPlugin


class AzureTTS(TTSPlugin):
    name = "azure"
    description = "Microsoft Azure Cognitive Services Text-to-Speech"

    def _get_default(self, key: str, fallback: str) -> str:
        return os.getenv(f"MSTTS_DEFAULT_{key.upper()}", fallback)

    def _build_ssml(
        self, text: str, voice: str, language: str, rate: str, pitch: str
    ) -> str:
        # `text` originated from RSS / WP / user input and may contain
        # bare ``&``, ``<``, ``>`` characters that would otherwise
        # break SSML parsing on the Azure side. Escape them.
        # Voice / language / rate / pitch come from validated config or
        # query strings and are not user prose; they don't need
        # escaping here.
        return (
            '<speak version="1.0"'
            f' xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{language}">'
            f'<voice name="{voice}">'
            f'<prosody rate="{rate}" pitch="{pitch}">'
            f"{xml_escape(text)}"
            "</prosody></voice></speak>"
        )

    def _resolve_defaults(
        self,
        voice: str | None,
        language: str | None,
        rate: str | None,
        pitch: str | None,
    ) -> tuple[str, str, str, str]:
        return (
            voice or self._get_default("voice", "en-US-EmmaMultilingualNeural"),
            language or self._get_default("language", "en-US"),
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
            voice, language, rate, pitch,
        )
        # When SSML is supplied verbatim, the cache key is the SSML
        # itself plus the voice/language for layout purposes only —
        # rate and pitch are baked into the SSML so we use placeholder
        # cache-key values.
        if ssml:
            return self.cache_path(ssml, language, voice, "ssml", "ssml")
        return self.cache_path(text, language, voice, rate, pitch)

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
            voice, language, rate, pitch,
        )
        cached = self.resolve_cache_path(
            text, ssml=ssml, voice=voice, language=language,
            rate=rate, pitch=pitch,
        )

        if cached.exists():
            async for chunk in self._stream_file(cached):
                yield chunk
            return

        cached.parent.mkdir(parents=True, exist_ok=True)

        final_ssml = ssml if ssml else self._build_ssml(text, voice, language, rate, pitch)
        audio_data = await self._synthesize_to_bytes(final_ssml, voice)

        # Atomic write: a reader checking ``cached.exists()`` (eg.
        # /queue, or trunk reading the file directly) must either
        # see the file absent or see it complete — never half-written.
        # Path.write_bytes opens the destination immediately, so we'd
        # otherwise race during the write. Write to a sibling .tmp
        # and rename: POSIX rename is atomic on the same filesystem.
        tmp_path = cached.with_suffix(cached.suffix + ".tmp")
        tmp_path.write_bytes(audio_data)
        tmp_path.replace(cached)

        chunk_size = 8192
        for i in range(0, len(audio_data), chunk_size):
            yield audio_data[i : i + chunk_size]

    async def _synthesize_to_bytes(self, ssml: str, voice: str) -> bytes:
        """Run the Azure Speech SDK synchronous synthesis in a thread."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._synthesize_sync, ssml, voice,
        )

    def _synthesize_sync(self, ssml: str, voice: str) -> bytes:
        key = os.getenv("MSTTS_SUBSCRIPTION_KEY", "")
        region = os.getenv("MSTTS_REGION", "eastus")

        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        speech_config.speech_synthesis_voice_name = voice
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
        )

        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=None
        )

        result = synthesizer.speak_ssml_async(ssml).get()

        if result.reason == speechsdk.ResultReason.Canceled:
            details = result.cancellation_details
            raise RuntimeError(
                f"Azure TTS synthesis canceled: {details.reason} — {details.error_details}"
            )

        return result.audio_data

    async def _stream_file(self, path: Path, chunk_size: int = 8192) -> AsyncIterator[bytes]:
        """Stream a cached WAV file in chunks."""
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, path.read_bytes)
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]
