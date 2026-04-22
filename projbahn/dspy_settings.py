from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DSPySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROJBAHN_DSPY_",
        extra="ignore",
    )

    temperature: float = Field(default=0.2)
    max_tokens: int = Field(default=1200)
    cache_enabled: bool = Field(default=True)
    mlflow_enabled: bool = Field(default=False)
    mlflow_tracking_uri: str = Field(default="http://127.0.0.1:5000")
    mlflow_experiment_name: str = Field(default="Projbahn DSPy")
