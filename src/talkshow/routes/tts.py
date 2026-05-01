"""Single endpoint for everything: synthesise speech audio.

`/speak` accepts content in three mutually-substitutable forms:

  ssml -> sent verbatim to the TTS engine
  text -> wrapped in an SSML envelope built from voice/lang/rate/pitch
  url  -> fetched via a source plugin (using offset + part), then
          synthesised as text

When more than one form is supplied, precedence is:

  ssml > text > url

so an explicit override always wins. Returns audio/wav.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..plugins import loader

router = APIRouter(tags=["TTS"])


class SpeakBody(BaseModel):
    ssml: str | None = Field(None, description="Raw SSML; sent verbatim")
    text: str | None = Field(None, description="Plain text to synthesise")
    url: str | None = Field(None, description="Source URL to fetch from")
    offset: int | None = Field(None, description="When url is an index, the article offset")
    part: str | None = Field(
        None,
        description="Which part of the source to speak: 'header' or 'body' (default body)",
    )
    voice: str | None = Field(None, description="Voice name (e.g. en-US-EmmaMultilingualNeural)")
    language: str | None = Field(None, description="Language code (e.g. en-US)")
    rate: str | None = Field(None, description="Speech rate (e.g. +10%)")
    pitch: str | None = Field(None, description="Speech pitch (e.g. -5%)")
    engine: str | None = Field(None, description="TTS engine plugin name")
    source: str | None = Field(None, description="Source plugin name (default: wordpress)")


async def _resolve_text(
    *,
    ssml: str | None,
    text: str | None,
    url: str | None,
    offset: int,
    part: str,
    source_name: str,
) -> tuple[str, str | None]:
    """Pick the synthesis input.

    Returns (text_for_tts, ssml_or_None). When SSML is set, the
    text return is empty -- the engine will use the SSML directly.
    """
    if ssml:
        return "", ssml
    if text:
        return text, None
    if url:
        plugin = loader.get_source(source_name)
        if not plugin:
            available = list(loader.list_sources().keys())
            raise HTTPException(
                status_code=404,
                detail=f"Source '{source_name}' not found. Available: {available}",
            )
        try:
            article = await plugin.fetch(url, offset=offset, part=part)
        except IndexError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Source fetch failed: {e}")
        return article.get("text", ""), None
    raise HTTPException(
        status_code=400,
        detail="provide one of: ssml, text, url",
    )


async def _do_synthesize(
    *,
    ssml: str | None,
    text: str | None,
    url: str | None,
    offset: int,
    part: str,
    voice: str | None,
    language: str | None,
    rate: str | None,
    pitch: str | None,
    engine_name: str,
    source_name: str,
) -> Response:
    final_text, final_ssml = await _resolve_text(
        ssml=ssml,
        text=text,
        url=url,
        offset=offset,
        part=part,
        source_name=source_name,
    )

    if not final_text and not final_ssml:
        raise HTTPException(
            status_code=400, detail="resolved input was empty",
        )

    plugin = loader.get_tts(engine_name)
    if not plugin:
        available = list(loader.list_tts().keys())
        raise HTTPException(
            status_code=404,
            detail=f"TTS engine '{engine_name}' not found. Available: {available}",
        )

    stream = plugin.synthesize(
        final_text,
        ssml=final_ssml,
        voice=voice,
        language=language,
        rate=rate,
        pitch=pitch,
    )

    chunks: list[bytes] = []
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
    summary="Synthesise speech audio",
    responses={
        200: {"content": {"audio/wav": {}}, "description": "WAV audio"},
        400: {"description": "Missing required input"},
        404: {"description": "Engine or source plugin not found"},
        502: {"description": "Source fetch or TTS synthesis failed"},
    },
)


@router.get(
    "/speak",
    description=(
        "Synthesise speech audio. Provide one of: `ssml` (verbatim), "
        "`text` (plain), or `url` (fetched via the configured source "
        "plugin). When `url` is used, `offset` selects which article "
        "from an index page and `part` picks 'header' (just the "
        "title/byline/date line) or 'body' (the article itself). "
        "Returns audio/wav."
    ),
    **_common,
)
async def synthesize_get(
    ssml: str | None = Query(None, description="Raw SSML"),
    text: str | None = Query(None, description="Plain text to synthesise"),
    url: str | None = Query(None, description="Source URL"),
    offset: int = Query(0, description="Article offset (when url is an index)"),
    part: str = Query("body", description="Which part to speak: 'header' or 'body'"),
    voice: str | None = Query(None, description="Voice name"),
    language: str | None = Query(None, description="Language code"),
    rate: str | None = Query(None, description="Speech rate"),
    pitch: str | None = Query(None, description="Speech pitch"),
    engine: str | None = Query(None, description="TTS engine plugin name"),
    source: str | None = Query(None, description="Source plugin name"),
):
    return await _do_synthesize(
        ssml=ssml,
        text=text,
        url=url,
        offset=offset,
        part=part,
        voice=voice,
        language=language,
        rate=rate,
        pitch=pitch,
        engine_name=engine or "azure",
        source_name=source or "wordpress",
    )


@router.post(
    "/speak",
    description=(
        "Synthesise speech audio. Same args as GET; query takes "
        "precedence over body when both supply a value."
    ),
    **_common,
)
async def synthesize_post(
    ssml: str | None = Query(None, description="Raw SSML"),
    text: str | None = Query(None, description="Plain text"),
    url: str | None = Query(None, description="Source URL"),
    offset: int | None = Query(None, description="Article offset"),
    part: str | None = Query(None, description="Which part to speak: 'header' or 'body'"),
    voice: str | None = Query(None, description="Voice name"),
    language: str | None = Query(None, description="Language code"),
    rate: str | None = Query(None, description="Speech rate"),
    pitch: str | None = Query(None, description="Speech pitch"),
    engine: str | None = Query(None, description="TTS engine plugin name"),
    source: str | None = Query(None, description="Source plugin name"),
    body: SpeakBody | None = None,
):
    final_ssml = ssml or (body.ssml if body else None)
    final_text = text or (body.text if body else None)
    final_url = url or (body.url if body else None)
    final_offset = offset if offset is not None else (body.offset if body else None)
    final_part = part or (body.part if body else None) or "body"
    final_voice = voice or (body.voice if body else None)
    final_language = language or (body.language if body else None)
    final_rate = rate or (body.rate if body else None)
    final_pitch = pitch or (body.pitch if body else None)
    engine_name = engine or (body.engine if body else None) or "azure"
    source_name = source or (body.source if body else None) or "wordpress"

    return await _do_synthesize(
        ssml=final_ssml,
        text=final_text,
        url=final_url,
        offset=final_offset or 0,
        part=final_part,
        voice=final_voice,
        language=final_language,
        rate=final_rate,
        pitch=final_pitch,
        engine_name=engine_name,
        source_name=source_name,
    )
