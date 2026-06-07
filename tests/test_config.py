"""Tests for talkshow.config.Settings."""

from __future__ import annotations

import pytest


def test_settings_defaults():
    """A fresh Settings with no env set carries the documented
    production defaults (Azure multilingual neural voice, eastus)."""
    from talkshow.config import Settings

    s = Settings()
    assert s.mstts_subscription_key == ""
    assert s.mstts_region == "eastus"
    assert s.mstts_default_voice == "en-US-EmmaMultilingualNeural"
    assert s.mstts_default_language == "en-US"
    assert s.mstts_default_rate == "0%"
    assert s.mstts_default_pitch == "0%"


def test_settings_reads_environment(monkeypatch):
    """Field values are overridable via (case-insensitive) env vars."""
    monkeypatch.setenv("MSTTS_SUBSCRIPTION_KEY", "secret-key")
    monkeypatch.setenv("MSTTS_REGION", "westus")
    monkeypatch.setenv("MSTTS_DEFAULT_VOICE", "en-GB-RyanNeural")

    from talkshow.config import Settings

    s = Settings()
    assert s.mstts_subscription_key == "secret-key"
    assert s.mstts_region == "westus"
    assert s.mstts_default_voice == "en-GB-RyanNeural"


def test_settings_ignores_unknown_env(monkeypatch):
    """`extra: ignore` means an unrelated env var doesn't blow up
    construction."""
    monkeypatch.setenv("SOME_UNRELATED_VAR", "whatever")

    from talkshow.config import Settings

    Settings()  # must not raise


def test_module_level_singleton():
    """The module exposes a ready-built ``settings`` instance."""
    from talkshow import config

    assert isinstance(config.settings, config.Settings)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
