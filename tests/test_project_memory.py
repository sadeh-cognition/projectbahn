from __future__ import annotations

import pytest
from model_bakery import baker

from projects.models import Project, ProjectLLMConfig
from projects.project_memory import _build_mem0_config


@pytest.mark.django_db
def test_build_mem0_config_uses_project_llm_name_for_llm_model() -> None:
    project = baker.make(Project)
    ProjectLLMConfig.objects.create(
        project=project,
        provider="groq",
        llm_name="llama-3.1-8b-instant",
    )

    config = _build_mem0_config(project=project)

    assert config["llm"]["config"]["model"] == "llama-3.1-8b-instant"
    assert config["embedder"]["config"]["model"]


@pytest.mark.django_db
def test_build_mem0_config_omits_llm_model_when_project_has_no_llm_name() -> None:
    project = baker.make(Project)

    config = _build_mem0_config(project=project)

    assert "model" not in config["llm"]["config"]
    assert config["embedder"]["config"]["model"]
