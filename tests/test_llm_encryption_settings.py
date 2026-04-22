from __future__ import annotations

import pytest

from pydantic import ValidationError

from projbahn.llm_encryption_settings import LLMEncryptionSettings


def test_llm_encryption_settings_requires_api_key_encryption_key(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY_ENCRYPTION_KEY", raising=False)

    with pytest.raises(ValidationError):
        LLMEncryptionSettings()


def test_llm_encryption_settings_reads_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY_ENCRYPTION_KEY", "custom-encryption-key")

    config = LLMEncryptionSettings()

    assert config.api_key_encryption_key == "custom-encryption-key"
