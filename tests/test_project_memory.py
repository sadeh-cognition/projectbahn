from __future__ import annotations

import pytest
from model_bakery import baker

from projects.models import Project, ProjectLLMConfig
from projbahn import settings as app_settings
from projects.project_memory import _build_mem0_config, _build_project_filters


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


def test_build_project_filters_uses_top_level_mem0_scope_keys() -> None:
    filters = _build_project_filters(project_id=42)

    assert filters == {
        "user_id": app_settings.mem0_settings.user_scope,
        "agent_id": "project-42",
    }
