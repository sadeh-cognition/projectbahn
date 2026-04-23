from __future__ import annotations

import pytest
from pathlib import Path

from pydantic import ValidationError

from projbahn.mem0_settings import Mem0Settings


def test_mem0_settings_uses_sane_defaults(monkeypatch) -> None:
    monkeypatch.delenv("PROJBAHN_MEM0_VERIFY_LMSTUDIO_ON_STARTUP", raising=False)
    monkeypatch.delenv("PROJBAHN_MEM0_STARTUP_TIMEOUT_SECONDS", raising=False)
    config = Mem0Settings(embedder_model="embed-default")

    assert config.chroma_path == str(Path(__file__).resolve().parent.parent / ".mem0_chroma")
    assert config.collection_name == "projectbahn"
    assert config.user_scope == "projectbahn"
    assert config.lmstudio_base_url == "http://127.0.0.1:1234/v1"
    assert config.embedder_model == "embed-default"
    assert config.embedding_dims == 1536
    assert config.verify_lmstudio_on_startup is True
    assert config.startup_timeout_seconds == 30
    assert config.search_limit == 8
    assert config.list_limit == 500


def test_mem0_settings_requires_embedder_model(monkeypatch) -> None:
    monkeypatch.delenv("PROJBAHN_MEM0_EMBEDDER_MODEL", raising=False)
    with pytest.raises(ValidationError):
        Mem0Settings()


def test_mem0_settings_reads_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("PROJBAHN_MEM0_CHROMA_PATH", "/tmp/custom-chroma")
    monkeypatch.setenv("PROJBAHN_MEM0_COLLECTION_NAME", "custom-collection")
    monkeypatch.setenv("PROJBAHN_MEM0_USER_SCOPE", "custom-scope")
    monkeypatch.setenv("PROJBAHN_MEM0_LMSTUDIO_BASE_URL", "http://lmstudio:1234/v1")
    monkeypatch.setenv("PROJBAHN_MEM0_EMBEDDER_MODEL", "embed-custom")
    monkeypatch.setenv("PROJBAHN_MEM0_EMBEDDING_DIMS", "768")
    monkeypatch.setenv("PROJBAHN_MEM0_VERIFY_LMSTUDIO_ON_STARTUP", "false")
    monkeypatch.setenv("PROJBAHN_MEM0_STARTUP_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("PROJBAHN_MEM0_SEARCH_LIMIT", "12")
    monkeypatch.setenv("PROJBAHN_MEM0_LIST_LIMIT", "250")

    config = Mem0Settings()

    assert config.chroma_path == "/tmp/custom-chroma"
    assert config.collection_name == "custom-collection"
    assert config.user_scope == "custom-scope"
    assert config.lmstudio_base_url == "http://lmstudio:1234/v1"
    assert config.embedder_model == "embed-custom"
    assert config.embedding_dims == 768
    assert config.verify_lmstudio_on_startup is False
    assert config.startup_timeout_seconds == 45
    assert config.search_limit == 12
    assert config.list_limit == 250
