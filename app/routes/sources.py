"""Source routes — fetch articles from datasource plugins."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..plugins import loader

router = APIRouter(tags=["Sources"])


class SourceBody(BaseModel):
    name: str | None = Field(
        None, description="Source plugin name (e.g. wordpress)",
    )
    url: str | None = Field(
        None, description="Source URL — single article or index page",
    )
    offset: int | None = Field(
        None, description="When url is an index, the 0-based offset",
    )
    summary: bool | None = Field(
        None, description="True for summary, False for full body",
    )


async def _do_fetch(
    source_name: str | None,
    source_url: str | None,
    offset: int,
    summary: bool,
):
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
        return await plugin.fetch(source_url, offset=offset, summary=summary)
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Source fetch failed: {e}")


_common = dict(
    summary="Fetch an article from a datasource",
    responses={
        200: {"description": "Article data"},
        400: {"description": "Missing required parameters"},
        404: {"description": "Source plugin not found"},
    },
)


@router.get(
    "/source",
    description=(
        "Fetch an article using query parameters only. The plugin "
        "decides whether the URL is an index or a single article. "
        "Pass `offset` to pick from an index, `summary=true` to "
        "return a summary instead of the full body."
    ),
    **_common,
)
async def fetch_article_get(
    name: str | None = Query(None, description="Source plugin name"),
    url: str | None = Query(None, description="Source URL"),
    offset: int | None = Query(None, description="Article index (0-based)"),
    summary: bool | None = Query(None, description="Summary vs full body"),
):
    return await _do_fetch(name, url, offset or 0, bool(summary))


@router.post(
    "/source",
    description=(
        "Fetch an article. Parameters can be passed via query "
        "string, JSON body, or both (query takes precedence)."
    ),
    **_common,
)
async def fetch_article_post(
    name: str | None = Query(None, description="Source plugin name"),
    url: str | None = Query(None, description="Source URL"),
    offset: int | None = Query(None, description="Article index (0-based)"),
    summary: bool | None = Query(None, description="Summary vs full body"),
    body: SourceBody | None = None,
):
    source_name = name or (body.name if body else None)
    source_url = url or (body.url if body else None)
    final_offset = offset if offset is not None else (body.offset if body else None)
    final_summary = summary if summary is not None else (body.summary if body else None)
    return await _do_fetch(
        source_name, source_url, final_offset or 0, bool(final_summary),
    )
