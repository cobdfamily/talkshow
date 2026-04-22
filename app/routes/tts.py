"""TTS route — synthesize text to speech and stream audio."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..plugins import loader

router = APIRouter(tags=["TTS"])


class TTSBody(BaseModel):
    text: str | None = Field(None, description="Text to synthesize")
    voice: str | None = Field(None, description="Voice name (e.g. en-US-EmmaMultilingualNeural)")
    language: str | None = Field(None, description="Language code (e.g. en-US)")
    rate: str | None = Field(None, description="Speech rate (e.g. +10%, -5%, 0%)")
    pitch: str | None = Field(None, description="Speech pitch (e.g. +5%, -10%, 0%)")
    engine: str | None = Field(None, description="TTS engine plugin name (default: azure)")


async def _do_synthesize(
    text: str | None,
    voice: str | None,
    language: str | None,
    rate: str | None,
    pitch: str | None,
    engine_name: str,
) -> Response:
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")

    plugin = loader.get_tts(engine_name)
    if not plugin:
        available = list(loader.list_tts().keys())
        raise HTTPException(
            status_code=404,
            detail=f"TTS engine '{engine_name}' not found. Available: {available}",
        )

    stream = plugin.synthesize(
        text, voice=voice, language=language, rate=rate, pitch=pitch
    )

    # Collect all audio chunks. The plugin already materializes the full audio
    # (either from synthesis or cache read) before yielding, so this doesn't
    # add memory overhead. A full Response with Content-Length is required for
    # Safari and other browsers to play the audio.
    chunks = []
    try:
        async for chunk in stream:
            chunks.append(chunk)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {e}")

    if not chunks:
        raise HTTPException(status_code=500, detail="TTS engine returned no audio")

    audio_data = b"".join(chunks)

    return Response(
        content=audio_data,
        media_type="audio/wav",
        headers={"Content-Length": str(len(audio_data))},
    )


_common = dict(
    summary="Synthesize text to speech",
    responses={
        200: {"content": {"audio/wav": {}}, "description": "WAV audio"},
        400: {"description": "No text provided"},
        404: {"description": "TTS engine not found"},
    },
)


@router.get(
    "/speak",
    description="Generate speech audio from text via query parameters. Returns WAV audio.",
    **_common,
)
async def synthesize_get(
    text: str | None = Query(None, description="Text to synthesize"),
    voice: str | None = Query(None, description="Voice name"),
    language: str | None = Query(None, description="Language code"),
    rate: str | None = Query(None, description="Speech rate"),
    pitch: str | None = Query(None, description="Speech pitch"),
    engine: str | None = Query(None, description="TTS engine plugin name"),
):
    return await _do_synthesize(text, voice, language, rate, pitch, engine or "azure")


@router.post(
    "/speak",
    description=(
        "Generate speech audio from text. Text can be provided via the `text` query "
        "parameter, the JSON body, or both (combined with a space, query first). "
        "Returns WAV audio."
    ),
    **_common,
)
async def synthesize_post(
    text: str | None = Query(None, description="Text to synthesize"),
    voice: str | None = Query(None, description="Voice name"),
    language: str | None = Query(None, description="Language code"),
    rate: str | None = Query(None, description="Speech rate"),
    pitch: str | None = Query(None, description="Speech pitch"),
    engine: str | None = Query(None, description="TTS engine plugin name"),
    body: TTSBody | None = None,
):
    # Combine text from query and body
    parts = []
    if text:
        parts.append(text)
    if body and body.text:
        parts.append(body.text)
    combined_text = " ".join(parts)

    # Merge params — query takes precedence, body fills gaps
    voice = voice or (body.voice if body else None)
    language = language or (body.language if body else None)
    rate = rate or (body.rate if body else None)
    pitch = pitch or (body.pitch if body else None)
    engine_name = engine or (body.engine if body else None) or "azure"

    return await _do_synthesize(combined_text, voice, language, rate, pitch, engine_name)
