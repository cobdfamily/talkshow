"""Source routes — fetch articles from datasource plugins."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..plugins import loader

router = APIRouter(tags=["Sources"])


class SourceBody(BaseModel):
    name: str | None = Field(None, description="Source plugin name (e.g. wordpress)")
    url: str | None = Field(None, description="Source URL (e.g. https://example.com)")
    articleOffset: int | None = Field(None, description="Article index to fetch (0-based)")


@router.post(
    "/source",
    summary="Fetch an article from a datasource",
    description=(
        "Fetch an article using a datasource plugin. Provide the plugin name, "
        "source URL, and article offset. Parameters can be passed via query "
        "string, JSON body, or both (query takes precedence)."
    ),
    responses={
        200: {"description": "Article data"},
        400: {"description": "Missing required parameters"},
        404: {"description": "Source plugin not found"},
    },
)
async def fetch_article(
    name: str | None = Query(None, description="Source plugin name"),
    url: str | None = Query(None, description="Source URL"),
    articleOffset: int | None = Query(None, description="Article index (0-based)"),
    body: SourceBody | None = None,
):
    source_name = name or (body.name if body else None)
    source_url = url or (body.url if body else None)
    offset = articleOffset if articleOffset is not None else (body.articleOffset if body else None)
    offset = offset or 0

    if not source_name:
        raise HTTPException(status_code=400, detail="'name' is required")
    if not source_url:
        raise HTTPException(status_code=400, detail="'url' is required")

    plugin = loader.get_source(source_name)
    if not plugin:
        available = list(loader.list_sources().keys())
        raise HTTPException(
            status_code=404,
            detail=f"Source '{source_name}' not found. Available: {available}",
        )

    try:
        return await plugin.fetch(source_url, article_offset=offset)
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Source fetch failed: {e}")


@router.post(
    "/source/list",
    summary="List articles from a datasource",
    description="List all available articles from a datasource plugin.",
    responses={
        200: {"description": "List of articles"},
        400: {"description": "Missing required parameters"},
        404: {"description": "Source plugin not found"},
    },
)
async def list_articles(
    name: str | None = Query(None, description="Source plugin name"),
    url: str | None = Query(None, description="Source URL"),
    body: SourceBody | None = None,
):
    source_name = name or (body.name if body else None)
    source_url = url or (body.url if body else None)

    if not source_name:
        raise HTTPException(status_code=400, detail="'name' is required")
    if not source_url:
        raise HTTPException(status_code=400, detail="'url' is required")

    plugin = loader.get_source(source_name)
    if not plugin:
        available = list(loader.list_sources().keys())
        raise HTTPException(
            status_code=404,
            detail=f"Source '{source_name}' not found. Available: {available}",
        )

    try:
        return await plugin.list_articles(source_url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Source fetch failed: {e}")
