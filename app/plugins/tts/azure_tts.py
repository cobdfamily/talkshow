"""Microsoft Azure TTS plugin.

Uses the Azure Cognitive Services Speech SDK for synthesis.
Handles caching and streaming per the plugin interface contract.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator

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
        return (
            '<speak version="1.0"'
            f' xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{language}">'
            f'<voice name="{voice}">'
            f'<prosody rate="{rate}" pitch="{pitch}">'
            f"{text}"
            "</prosody></voice></speak>"
        )

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> AsyncIterator[bytes]:
        voice = voice or self._get_default("voice", "en-US-EmmaMultilingualNeural")
        language = language or self._get_default("language", "en-US")
        rate = rate or self._get_default("rate", "0%")
        pitch = pitch or self._get_default("pitch", "0%")

        cached = self.cache_path(text, language, voice, rate, pitch)

        if cached.exists():
            async for chunk in self._stream_file(cached):
                yield chunk
            return

        cached.parent.mkdir(parents=True, exist_ok=True)

        audio_data = await self._synthesize_to_bytes(text, voice, language, rate, pitch)

        cached.write_bytes(audio_data)

        chunk_size = 8192
        for i in range(0, len(audio_data), chunk_size):
            yield audio_data[i : i + chunk_size]

    async def _synthesize_to_bytes(
        self, text: str, voice: str, language: str, rate: str, pitch: str
    ) -> bytes:
        """Run the Azure Speech SDK synchronous synthesis in a thread."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._synthesize_sync, text, voice, language, rate, pitch
        )

    def _synthesize_sync(
        self, text: str, voice: str, language: str, rate: str, pitch: str
    ) -> bytes:
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

        ssml = self._build_ssml(text, voice, language, rate, pitch)
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
