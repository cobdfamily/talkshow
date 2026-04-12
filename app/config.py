"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mstts_subscription_key: str = ""
    mstts_region: str = "eastus"
    mstts_default_voice: str = "en-US-EmmaMultilingualNeural"
    mstts_default_language: str = "en-US"
    mstts_default_rate: str = "0%"
    mstts_default_pitch: str = "0%"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
