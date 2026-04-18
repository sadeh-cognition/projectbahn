from __future__ import annotations

from ninja.testing import TestClient

import pytest
from model_bakery import baker

from projects.api import api
from projects.models import Project
from projects.schemas import (
    ProjectCreateSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
)

client = TestClient(api)


@pytest.fixture
def project() -> Project:
    return baker.make(Project, name="Existing Project", description="Initial description")


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


@pytest.mark.django_db
def test_list_projects(project: Project) -> None:
    response = client.get("/projects")

    assert response.status_code == 200
    body = [ProjectResponseSchema.model_validate(item) for item in response.json()]
    assert len(body) == 1
    assert body[0].id == project.id
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


@pytest.mark.django_db
def test_delete_project(project: Project) -> None:
    response = client.delete(f"/projects/{project.id}")

    assert response.status_code == 204
    assert not Project.objects.filter(id=project.id).exists()
