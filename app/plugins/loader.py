"""Plugin discovery and registration.

Scans each plugin subdirectory, imports modules, and collects instances
of TTSPlugin, SourcePlugin, and OutputPlugin.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from .base import OutputPlugin, SourcePlugin, TTSPlugin

_tts_plugins: dict[str, TTSPlugin] = {}
_source_plugins: dict[str, SourcePlugin] = {}
_output_plugins: dict[str, OutputPlugin] = {}


def _scan_package(package_path: str, package_name: str) -> list:
    """Import all modules in a package directory and return their contents."""
    modules = []
    for importer, modname, _ispkg in pkgutil.iter_modules([package_path]):
        module = importlib.import_module(f"{package_name}.{modname}")
        modules.append(module)
    return modules


def register_tts(plugin: TTSPlugin) -> None:
    _tts_plugins[plugin.name] = plugin


def register_source(plugin: SourcePlugin) -> None:
    _source_plugins[plugin.name] = plugin


def register_output(plugin: OutputPlugin) -> None:
    _output_plugins[plugin.name] = plugin


def get_tts(name: str) -> TTSPlugin | None:
    return _tts_plugins.get(name)


def get_source(name: str) -> SourcePlugin | None:
    return _source_plugins.get(name)


def get_output(name: str) -> OutputPlugin | None:
    return _output_plugins.get(name)


def list_tts() -> dict[str, TTSPlugin]:
    return dict(_tts_plugins)


def list_sources() -> dict[str, SourcePlugin]:
    return dict(_source_plugins)


def list_outputs() -> dict[str, OutputPlugin]:
    return dict(_output_plugins)


def load_all() -> None:
    """Discover and load all plugins from the tts/, sources/, and outputs/ dirs."""
    plugins_dir = Path(__file__).parent

    for subdir, base_class, register_fn in [
        ("tts", TTSPlugin, register_tts),
        ("sources", SourcePlugin, register_source),
        ("outputs", OutputPlugin, register_output),
    ]:
        pkg_path = str(plugins_dir / subdir)
        pkg_name = f"app.plugins.{subdir}"
        modules = _scan_package(pkg_path, pkg_name)

        for module in modules:
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, base_class)
                    and attr is not base_class
                ):
                    instance = attr()
                    register_fn(instance)
