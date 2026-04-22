from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMEncryptionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
    )

    api_key_encryption_key: str = Field(validation_alias="LLM_API_KEY_ENCRYPTION_KEY")
