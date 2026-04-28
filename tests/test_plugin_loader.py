"""Tests for plugin discovery and registration."""

from talkshow.plugins import loader
from talkshow.plugins.base import SourcePlugin, TTSPlugin


class TestPluginLoader:
    def setup_method(self):
        """Reset plugin registries before each test."""
        loader._tts_plugins.clear()
        loader._source_plugins.clear()

    def test_load_all_discovers_bundled_plugins(self):
        loader.load_all()

        tts = loader.list_tts()
        assert "azure" in tts
        assert isinstance(tts["azure"], TTSPlugin)

        sources = loader.list_sources()
        assert "wordpress" in sources
        assert isinstance(sources["wordpress"], SourcePlugin)

    def test_get_tts_returns_none_for_unknown(self):
        loader.load_all()
        assert loader.get_tts("nonexistent") is None

    def test_get_source_returns_none_for_unknown(self):
        loader.load_all()
        assert loader.get_source("nonexistent") is None

    def test_register_and_get_tts(self):
        from tests.test_plugins_base import StubTTS
        plugin = StubTTS()
        loader.register_tts(plugin)
        assert loader.get_tts("stub") is plugin

    def test_register_and_get_source(self):
        from tests.test_plugins_base import StubSource
        plugin = StubSource()
        loader.register_source(plugin)
        assert loader.get_source("stub") is plugin
