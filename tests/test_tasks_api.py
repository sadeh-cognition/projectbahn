from __future__ import annotations

from django.contrib.auth import get_user_model

from ninja.testing import TestClient

import pytest
from model_bakery import baker

from projects.api import api
from projects.models import Feature, Project, Task
from projects.schemas import TaskCreateSchema, TaskResponseSchema, TaskUpdateSchema

client = TestClient(api)
User = get_user_model()


@pytest.fixture
def project() -> Project:
    return baker.make(Project, name="Core Platform", description="Main platform project")


@pytest.fixture
def feature(project: Project) -> Feature:
    return baker.make(
        Feature,
        project=project,
        parent_feature=None,
        name="Authentication",
        description="Shared authentication feature",
    )


@pytest.fixture
def user():
    return baker.make(User)


@pytest.fixture
def other_user():
    return baker.make(User)


@pytest.fixture
def task(feature: Feature, user) -> Task:
    return baker.make(
        Task,
        feature=feature,
        user=user,
        title="Review API contract",
        description="Validate the payload shape before frontend implementation.",
        status="Waiting on backend API review.",
    )


@pytest.mark.django_db
def test_create_task(feature: Feature, user) -> None:
    payload = TaskCreateSchema(
        feature_id=feature.id,
        user_id=user.id,
        title="Handle rollout plan",
        description="Document scope and rollout order.",
        status="Blocked by deployment freeze.",
    )

    response = client.post("/tasks", json=payload.model_dump())

    assert response.status_code == 200
    body = TaskResponseSchema.model_validate(response.json())
    assert body.project_id == feature.project_id
    assert body.project_name == feature.project.name
    assert body.feature_id == feature.id
    assert body.feature_name == feature.name
    assert body.user_id == user.id
    assert body.user_username == user.username
    assert body.title == payload.title
    assert body.description == payload.description
    assert body.status == payload.status
    assert Task.objects.filter(id=body.id).exists()


@pytest.mark.django_db
def test_list_tasks(task: Task) -> None:
    response = client.get("/tasks")

    assert response.status_code == 200
    body = [TaskResponseSchema.model_validate(item) for item in response.json()]
    assert len(body) == 1
    assert body[0].id == task.id
    assert body[0].title == task.title
    assert body[0].status == task.status


@pytest.mark.django_db
def test_get_task(task: Task) -> None:
    response = client.get(f"/tasks/{task.id}")

    assert response.status_code == 200
    body = TaskResponseSchema.model_validate(response.json())
    assert body.id == task.id
    assert body.title == task.title
    assert body.description == task.description
    assert body.feature_id == task.feature_id
    assert body.user_id == task.user_id


@pytest.mark.django_db
def test_update_task(task: Task, feature: Feature, other_user) -> None:
    payload = TaskUpdateSchema(
        feature_id=feature.id,
        user_id=other_user.id,
        title="Ship UI wiring",
        description="Connect the page to the API.",
        status="In progress after API contract review.",
    )

    response = client.put(f"/tasks/{task.id}", json=payload.model_dump())

    assert response.status_code == 200
    body = TaskResponseSchema.model_validate(response.json())
    task.refresh_from_db()
    assert body.user_id == other_user.id
    assert body.title == payload.title
    assert body.description == payload.description
    assert body.status == payload.status
    assert task.user_id == other_user.id
    assert task.title == payload.title
    assert task.description == payload.description
    assert task.status == payload.status


@pytest.mark.django_db
def test_delete_task(task: Task) -> None:
    response = client.delete(f"/tasks/{task.id}")

    assert response.status_code == 204
    assert not Task.objects.filter(id=task.id).exists()


@pytest.mark.django_db
def test_list_tasks_filters_by_project_and_sorts_by_title(user) -> None:
    first_project = baker.make(Project, name="Alpha", description="First")
    second_project = baker.make(Project, name="Beta", description="Second")
    alpha_feature = baker.make(
        Feature,
        project=first_project,
        parent_feature=None,
        name="Alpha Feature",
        description="Alpha feature",
    )
    baker.make(
        Task,
        feature=alpha_feature,
        user=user,
        title="Write docs",
        description="Documentation",
        status="Done",
    )
    baker.make(
        Task,
        feature=alpha_feature,
        user=user,
        title="Add auth",
        description="Authentication work",
        status="In progress",
    )
    beta_feature = baker.make(
        Feature,
        project=second_project,
        parent_feature=None,
        name="Beta Feature",
        description="Beta feature",
    )
    baker.make(
        Task,
        feature=beta_feature,
        user=user,
        title="External task",
        description="Should not be returned",
        status="Todo",
    )

    response = client.get(
        f"/tasks?project_id={first_project.id}&sort_by=title&sort_dir=asc&search=auth",
    )

    assert response.status_code == 200
    body = [TaskResponseSchema.model_validate(item) for item in response.json()]
    assert [(item.project_id, item.title) for item in body] == [(first_project.id, "Add auth")]
