"""Plugin discovery routes — list available plugins."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..plugins import loader

router = APIRouter(tags=["Plugins"])


@router.get(
    "/plugins",
    summary="List all plugins",
    description="Returns all registered plugins grouped by type.",
)
async def list_all_plugins():
    return {
        "tts": [
            {"name": p.name, "description": p.description}
            for p in loader.list_tts().values()
        ],
        "sources": [
            {"name": p.name, "description": p.description}
            for p in loader.list_sources().values()
        ],
    }


@router.get(
    "/plugins/{plugin_type}",
    summary="List plugins by type",
    description="Returns registered plugins for a specific type (tts, sources).",
)
async def list_plugins_by_type(plugin_type: str):
    registry = {
        "tts": loader.list_tts,
        "sources": loader.list_sources,
    }

    getter = registry.get(plugin_type)
    if not getter:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown plugin type '{plugin_type}'. Use: tts, sources",
        )

    plugins = getter()
    return {
        plugin_type: [
            {"name": p.name, "description": p.description}
            for p in plugins.values()
        ],
    }
