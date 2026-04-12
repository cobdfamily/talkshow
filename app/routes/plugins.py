"""Plugin discovery routes — list available plugins."""

from __future__ import annotations

from fastapi import APIRouter

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
        "outputs": [
            {"name": p.name, "description": p.description, "content_type": p.content_type}
            for p in loader.list_outputs().values()
        ],
    }


@router.get(
    "/plugins/{plugin_type}",
    summary="List plugins by type",
    description="Returns registered plugins for a specific type (tts, sources, outputs).",
)
async def list_plugins_by_type(plugin_type: str):
    registry = {
        "tts": loader.list_tts,
        "sources": loader.list_sources,
        "outputs": loader.list_outputs,
    }

    getter = registry.get(plugin_type)
    if not getter:
        return {"error": f"Unknown plugin type '{plugin_type}'. Use: tts, sources, outputs"}

    plugins = getter()
    result = [{"name": p.name, "description": p.description} for p in plugins.values()]
    return {plugin_type: result}
