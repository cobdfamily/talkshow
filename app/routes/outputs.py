"""Output routes — render articles into non-audio formats."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..plugins import loader

router = APIRouter(tags=["Outputs"])


class OutputBody(BaseModel):
    format: str | None = Field(None, description="Output plugin name (e.g. twilio_xml)")
    source_name: str | None = Field(None, description="Source plugin to fetch articles from")
    source_url: str | None = Field(None, description="Source URL")
    voice: str | None = Field(None, description="Voice for TTS references")
    language: str | None = Field(None, description="Language for TTS references")


@router.post(
    "/output/{format_name}",
    summary="Render articles into an output format",
    description=(
        "Fetch articles from a source plugin and render them using an output "
        "formatter (e.g. Twilio XML / Signalwire LAML)."
    ),
    responses={
        200: {"description": "Formatted output"},
        400: {"description": "Missing required parameters"},
        404: {"description": "Plugin not found"},
    },
)
async def render_output(
    format_name: str,
    request: Request,
    source_name: str | None = Query(None, description="Source plugin name"),
    source_url: str | None = Query(None, description="Source URL"),
    voice: str | None = Query(None, description="Voice for TTS references"),
    language: str | None = Query(None, description="Language for TTS references"),
    body: OutputBody | None = None,
):
    src_name = source_name or (body.source_name if body else None)
    src_url = source_url or (body.source_url if body else None)
    voice = voice or (body.voice if body else None)
    language = language or (body.language if body else None)

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
        articles = await source_plugin.list_articles(src_url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Source fetch failed: {e}")

    tts_base_url = str(request.base_url).rstrip("/")
    content = await output_plugin.render(
        articles, tts_base_url=tts_base_url, voice=voice, language=language
    )

    return Response(content=content, media_type=output_plugin.content_type)
