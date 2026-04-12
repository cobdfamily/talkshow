"""TTS route — synthesize text to speech and stream audio."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
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


@router.post(
    "/tts",
    summary="Synthesize text to speech",
    description=(
        "Generate speech audio from text. Text can be provided via the `text` query "
        "parameter, the JSON body, or both (combined with a space, query first). "
        "Returns a WAV audio stream."
    ),
    response_class=StreamingResponse,
    responses={
        200: {"content": {"audio/wav": {}}, "description": "WAV audio stream"},
        400: {"description": "No text provided"},
        404: {"description": "TTS engine not found"},
    },
)
async def synthesize(
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

    if not combined_text:
        raise HTTPException(status_code=400, detail="No text provided")

    # Merge params — query takes precedence, body fills gaps
    voice = voice or (body.voice if body else None)
    language = language or (body.language if body else None)
    rate = rate or (body.rate if body else None)
    pitch = pitch or (body.pitch if body else None)
    engine_name = engine or (body.engine if body else None) or "azure"

    plugin = loader.get_tts(engine_name)
    if not plugin:
        available = list(loader.list_tts().keys())
        raise HTTPException(
            status_code=404,
            detail=f"TTS engine '{engine_name}' not found. Available: {available}",
        )

    stream = plugin.synthesize(
        combined_text, voice=voice, language=language, rate=rate, pitch=pitch
    )

    # Pull the first chunk before committing to a StreamingResponse so that
    # synthesis errors (bad credentials, network issues) return a proper HTTP
    # error instead of a broken stream.
    try:
        first_chunk = await stream.__anext__()
    except StopAsyncIteration:
        raise HTTPException(status_code=500, detail="TTS engine returned no audio")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {e}")

    async def _stream():
        yield first_chunk
        async for chunk in stream:
            yield chunk

    return StreamingResponse(_stream(), media_type="audio/wav")
