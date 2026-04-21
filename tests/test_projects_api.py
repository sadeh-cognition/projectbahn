from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password

from ninja.testing import TestClient

import pytest
from model_bakery import baker

from projects.api import api
from projects.models import EventLog, Feature, Project, ProjectLLMConfig, Task
from projects.schemas import (
    ProjectCreateSchema,
    ProjectLLMConfigResponseSchema,
    ProjectLLMConfigUpdateSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
)

client = TestClient(api)
User = get_user_model()


@pytest.fixture
def project() -> Project:
    return baker.make(Project, name="Existing Project", description="Initial description")


@pytest.fixture
def user() -> User:
    return baker.make(User, username="alex")


@pytest.mark.django_db
def test_create_project() -> None:
    payload = ProjectCreateSchema(
        name="Build API",
        description="Create the project CRUD endpoints.",
    )

    response = client.post("/projects", json=payload.model_dump())

    assert response.status_code == 200
    body = ProjectResponseSchema.model_validate(response.json())
    assert body.name == payload.name
    assert body.description == payload.description
    assert Project.objects.filter(id=body.id).exists()
    event_log = EventLog.objects.get(
        entity_type=EventLog.EntityType.PROJECT,
        entity_id=body.id,
        event_type=EventLog.EventType.CREATED,
    )
    assert event_log.event_details == {}


@pytest.mark.django_db
def test_list_projects(project: Project) -> None:
    response = client.get("/projects")

    assert response.status_code == 200
    body = [ProjectResponseSchema.model_validate(item) for item in response.json()]
    assert len(body) == 1
    assert body[0].id == project.id
    assert body[0].entity_type == EventLog.EntityType.PROJECT
    assert body[0].name == project.name


@pytest.mark.django_db
def test_get_project(project: Project) -> None:
    response = client.get(f"/projects/{project.id}")

    assert response.status_code == 200
    body = ProjectResponseSchema.model_validate(response.json())
    assert body.id == project.id
    assert body.description == project.description


@pytest.mark.django_db
def test_update_project(project: Project) -> None:
    payload = ProjectUpdateSchema(
        name="Updated Project",
        description="Updated description",
    )

    response = client.put(f"/projects/{project.id}", json=payload.model_dump())

    assert response.status_code == 200
    body = ProjectResponseSchema.model_validate(response.json())
    project.refresh_from_db()
    assert body.name == payload.name
    assert project.name == payload.name
    assert project.description == payload.description
    event_log = EventLog.objects.get(
        entity_type=EventLog.EntityType.PROJECT,
        entity_id=project.id,
        event_type=EventLog.EventType.MODIFIED,
    )
    assert event_log.event_details == {
        "name": {"old": "Existing Project", "new": payload.name},
        "description": {"old": "Initial description", "new": payload.description},
    }


@pytest.mark.django_db
def test_get_project_llm_config_defaults_when_missing(project: Project) -> None:
    response = client.get(f"/projects/{project.id}/llm-config")

    assert response.status_code == 200
    body = ProjectLLMConfigResponseSchema.model_validate(response.json())
    assert body.project_id == project.id
    assert body.provider == ""
    assert body.llm_name == ""
    assert body.api_key_configured is False
    assert body.api_key_usable is False
    assert body.api_key_requires_reentry is False


@pytest.mark.django_db
def test_update_project_llm_config_requires_auth(project: Project) -> None:
    payload = ProjectLLMConfigUpdateSchema(
        provider="groq",
        llm_name="llama-3.1-8b-instant",
        api_key="super-secret-key",
    )

    response = client.put(f"/projects/{project.id}/llm-config", json=payload.model_dump())

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."
    assert not ProjectLLMConfig.objects.filter(project=project).exists()


@pytest.mark.django_db
def test_update_project_llm_config_encrypts_and_hashes_api_key(project: Project, user: User) -> None:
    payload = ProjectLLMConfigUpdateSchema(
        provider="groq",
        llm_name="llama-3.1-8b-instant",
        api_key="super-secret-key",
    )

    response = client.put(f"/projects/{project.id}/llm-config", json=payload.model_dump(), user=user)

    assert response.status_code == 200
    body = ProjectLLMConfigResponseSchema.model_validate(response.json())
    assert body.project_id == project.id
    assert body.provider == payload.provider
    assert body.llm_name == payload.llm_name
    assert body.api_key_configured is True
    assert body.api_key_usable is True
    assert body.api_key_requires_reentry is False
    config = ProjectLLMConfig.objects.get(project=project)
    assert config.api_key_hash != payload.api_key
    assert config.encrypted_api_key != payload.api_key
    assert check_password(payload.api_key, config.api_key_hash)
    assert config.get_api_key() == payload.api_key


@pytest.mark.django_db
def test_update_project_llm_config_keeps_existing_api_key_when_blank(project: Project, user: User) -> None:
    config = ProjectLLMConfig.objects.create(
        project=project,
        provider="groq",
        llm_name="llama-3.1-8b-instant",
    )
    config.set_api_key("existing-key")
    config.save(update_fields=["api_key_hash", "encrypted_api_key", "date_updated"])
    original_hash = config.api_key_hash
    original_encrypted_key = config.encrypted_api_key
    payload = ProjectLLMConfigUpdateSchema(
        provider="openai",
        llm_name="gpt-5.4-mini",
        api_key="",
    )

    response = client.put(f"/projects/{project.id}/llm-config", json=payload.model_dump(), user=user)

    assert response.status_code == 200
    body = ProjectLLMConfigResponseSchema.model_validate(response.json())
    assert body.provider == payload.provider
    assert body.llm_name == payload.llm_name
    assert body.api_key_configured is True
    assert body.api_key_usable is True
    config.refresh_from_db()
    assert config.api_key_hash == original_hash
    assert config.encrypted_api_key == original_encrypted_key


@pytest.mark.django_db
def test_get_project_llm_config_marks_legacy_hashed_key_as_reentry_required(project: Project) -> None:
    ProjectLLMConfig.objects.create(
        project=project,
        provider="groq",
        llm_name="llama-3.1-8b-instant",
        api_key_hash=make_password("legacy-only"),
        encrypted_api_key="",
    )

    response = client.get(f"/projects/{project.id}/llm-config")

    assert response.status_code == 200
    body = ProjectLLMConfigResponseSchema.model_validate(response.json())
    assert body.api_key_configured is True
    assert body.api_key_usable is False
    assert body.api_key_requires_reentry is True


@pytest.mark.django_db
def test_delete_project(project: Project) -> None:
    feature = baker.make(
        Feature,
        project=project,
        parent_feature=None,
        name="Project feature",
        description="Feature removed with the project",
    )
    task = baker.make(
        Task,
        feature=feature,
        title="Project task",
        description="Task removed with the project",
        status="Todo",
    )

    response = client.delete(f"/projects/{project.id}")

    assert response.status_code == 204
    assert not Project.objects.filter(id=project.id).exists()
    assert not Feature.objects.filter(id=feature.id).exists()
    assert not Task.objects.filter(id=task.id).exists()
    logged_events = list(
        EventLog.objects.order_by("id").values_list("entity_type", "entity_id", "event_type")
    )
    assert logged_events == [
        (EventLog.EntityType.TASK, task.id, EventLog.EventType.DELETED),
        (EventLog.EntityType.FEATURE, feature.id, EventLog.EventType.DELETED),
        (EventLog.EntityType.PROJECT, project.id, EventLog.EventType.DELETED),
    ]
