from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mem0Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROJBAHN_MEM0_",
        extra="ignore",
    )

    chroma_path: str = Field(
        default_factory=lambda: str(Path(__file__).resolve().parent.parent / ".mem0_chroma")
    )
    collection_name: str = Field(default="projectbahn")
    user_scope: str = Field(default="projectbahn")
    lmstudio_base_url: str = Field(default="http://127.0.0.1:1234/v1")
    embedder_model: str
    embedding_dims: int = Field(default=1536)
    verify_lmstudio_on_startup: bool = Field(default=True)
    startup_timeout_seconds: int = Field(default=30)
    search_limit: int = Field(default=8)
    list_limit: int = Field(default=500)
