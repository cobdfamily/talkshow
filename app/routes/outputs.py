"""Output routes — render an article into a non-audio format."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..plugins import loader

router = APIRouter(tags=["Outputs"])


class OutputBody(BaseModel):
    source_name: str | None = Field(
        None, description="Source plugin to fetch from",
    )
    source_url: str | None = Field(None, description="Source URL")
    voice: str | None = Field(None, description="Voice for TTS references")
    language: str | None = Field(None, description="Language for TTS references")
    offset: int | None = Field(None, description="Article index (0-based)")
    summary: bool | None = Field(None, description="Summary vs full body")


async def _do_render(
    format_name: str,
    request: Request,
    src_name: str | None,
    src_url: str | None,
    voice: str | None,
    language: str | None,
    offset: int,
    summary: bool,
) -> Response:
    output_plugin = loader.get_output(format_name)
    if not output_plugin:
        available = list(loader.list_outputs().keys())
        raise HTTPException(
            status_code=404,
            detail=f"Output format '{format_name}' not found. Available: {available}",
        )

    if not src_name or not src_url:
        raise HTTPException(
            status_code=400,
            detail="'source_name' and 'source_url' are required",
        )

    source_plugin = loader.get_source(src_name)
    if not source_plugin:
        available = list(loader.list_sources().keys())
        raise HTTPException(
            status_code=404,
            detail=f"Source '{src_name}' not found. Available: {available}",
        )

    try:
        article = await source_plugin.fetch(
            src_url, offset=offset, summary=summary,
        )
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Source fetch failed: {e}")

    tts_base_url = str(request.base_url).rstrip("/")
    content = await output_plugin.render(
        article, tts_base_url=tts_base_url, voice=voice, language=language,
    )

    return Response(content=content, media_type=output_plugin.content_type)


_common = dict(
    summary="Render an article into an output format",
    responses={
        200: {"description": "Formatted output"},
        400: {"description": "Missing required parameters"},
        404: {"description": "Plugin not found"},
    },
)


@router.get(
    "/output/{format_name}",
    description="Render an article into an output format. Query-only.",
    **_common,
)
async def render_output_get(
    format_name: str,
    request: Request,
    source_name: str | None = Query(None, description="Source plugin name"),
    source_url: str | None = Query(None, description="Source URL"),
    voice: str | None = Query(None, description="Voice for TTS references"),
    language: str | None = Query(None, description="Language for TTS references"),
    offset: int = Query(0, description="Article index (0-based)"),
    summary: bool = Query(False, description="Summary vs full body"),
):
    return await _do_render(
        format_name, request, source_name, source_url,
        voice, language, offset, summary,
    )


@router.post(
    "/output/{format_name}",
    description=(
        "Fetch one article from a source plugin and render it via an "
        "output formatter (e.g. Twilio XML / SignalWire LAML). "
        "Parameters can be passed via query string, JSON body, or "
        "both (query takes precedence)."
    ),
    **_common,
)
async def render_output_post(
    format_name: str,
    request: Request,
    source_name: str | None = Query(None, description="Source plugin name"),
    source_url: str | None = Query(None, description="Source URL"),
    voice: str | None = Query(None, description="Voice for TTS references"),
    language: str | None = Query(None, description="Language for TTS references"),
    offset: int | None = Query(None, description="Article index (0-based)"),
    summary: bool | None = Query(None, description="Summary vs full body"),
    body: OutputBody | None = None,
):
    src_name = source_name or (body.source_name if body else None)
    src_url = source_url or (body.source_url if body else None)
    voice = voice or (body.voice if body else None)
    language = language or (body.language if body else None)
    final_offset = offset if offset is not None else (body.offset if body else None)
    final_summary = summary if summary is not None else (body.summary if body else None)

    return await _do_render(
        format_name, request, src_name, src_url, voice, language,
        final_offset or 0, bool(final_summary),
    )
