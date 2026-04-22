"""Output routes — render articles into non-audio formats."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..plugins import loader

OutputMode = Literal["full", "summary", "nextArticle"]

router = APIRouter(tags=["Outputs"])


class OutputBody(BaseModel):
    format: str | None = Field(None, description="Output plugin name (e.g. twilio_xml)")
    source_name: str | None = Field(None, description="Source plugin to fetch articles from")
    source_url: str | None = Field(None, description="Source URL")
    voice: str | None = Field(None, description="Voice for TTS references")
    language: str | None = Field(None, description="Language for TTS references")
    articleOffset: int | None = Field(None, description="Article index (0-based, used by full/nextArticle)")
    mode: OutputMode | None = Field(None, description="Mode: 'full', 'summary', or 'nextArticle'")


async def _do_render(
    format_name: str,
    request: Request,
    src_name: str | None,
    src_url: str | None,
    voice: str | None,
    language: str | None,
    article_offset: int,
    mode: OutputMode,
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
        if mode == "summary":
            articles = await source_plugin.list_articles(src_url)
        elif mode == "nextArticle":
            articles = [await source_plugin.fetch(src_url, article_offset=article_offset + 1)]
        else:
            articles = [await source_plugin.fetch(src_url, article_offset=article_offset)]
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Source fetch failed: {e}")

    tts_base_url = str(request.base_url).rstrip("/")
    content = await output_plugin.render(
        articles, tts_base_url=tts_base_url, voice=voice, language=language, mode=mode
    )

    return Response(content=content, media_type=output_plugin.content_type)


_common = dict(
    summary="Render articles into an output format",
    responses={
        200: {"description": "Formatted output"},
        400: {"description": "Missing required parameters"},
        404: {"description": "Plugin not found"},
    },
)


@router.get(
    "/output/{format_name}",
    description="Render articles into an output format using query parameters only.",
    **_common,
)
async def render_output_get(
    format_name: str,
    request: Request,
    source_name: str | None = Query(None, description="Source plugin name"),
    source_url: str | None = Query(None, description="Source URL"),
    voice: str | None = Query(None, description="Voice for TTS references"),
    language: str | None = Query(None, description="Language for TTS references"),
    articleOffset: int = Query(0, description="Article index (0-based, used by full/nextArticle)"),
    mode: OutputMode = Query("full", description="Mode: 'full', 'summary', or 'nextArticle'"),
):
    return await _do_render(
        format_name, request, source_name, source_url, voice, language, articleOffset, mode
    )


@router.post(
    "/output/{format_name}",
    description=(
        "Fetch articles from a source plugin and render them using an output "
        "formatter (e.g. Twilio XML / Signalwire LAML). Parameters can be passed "
        "via query string, JSON body, or both (query takes precedence)."
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
    articleOffset: int | None = Query(None, description="Article index (0-based)"),
    mode: OutputMode | None = Query(None, description="Mode: 'full', 'summary', or 'nextArticle'"),
    body: OutputBody | None = None,
):
    src_name = source_name or (body.source_name if body else None)
    src_url = source_url or (body.source_url if body else None)
    voice = voice or (body.voice if body else None)
    language = language or (body.language if body else None)
    offset = articleOffset if articleOffset is not None else (body.articleOffset if body else None) or 0
    resolved_mode = mode or (body.mode if body else None) or "full"

    return await _do_render(
        format_name, request, src_name, src_url, voice, language, offset, resolved_mode
    )
