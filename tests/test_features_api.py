from __future__ import annotations

from ninja.testing import TestClient

import pytest
from model_bakery import baker

from projects.api import api
from projects.models import EventLog, Feature, Project, Task
from projects.schemas import (
    FeatureCreateSchema,
    FeatureResponseSchema,
    FeatureUpdateSchema,
)

client = TestClient(api)


@pytest.fixture
def project() -> Project:
    return baker.make(Project, name="Core Platform", description="Main platform project")


@pytest.fixture
def other_project() -> Project:
    return baker.make(Project, name="Mobile App", description="Secondary project")


@pytest.fixture
def parent_feature(project: Project) -> Feature:
    return baker.make(
        Feature,
        project=project,
        parent_feature=None,
        name="Authentication",
        description="Shared authentication feature",
    )


@pytest.fixture
def feature(project: Project, parent_feature: Feature) -> Feature:
    return baker.make(
        Feature,
        project=project,
        parent_feature=parent_feature,
        name="OAuth Login",
        description="Allow sign in with external providers",
    )


@pytest.mark.django_db
def test_create_feature(project: Project, parent_feature: Feature) -> None:
    payload = FeatureCreateSchema(
        project_id=project.id,
        parent_feature_id=parent_feature.id,
        name="Password Reset",
        description="Allow users to reset forgotten passwords.",
    )

    response = client.post("/features", json=payload.model_dump())

    assert response.status_code == 200
    body = FeatureResponseSchema.model_validate(response.json())
    assert body.project_id == project.id
    assert body.parent_feature_id == parent_feature.id
    assert body.name == payload.name
    assert Feature.objects.filter(id=body.id).exists()
    event_log = EventLog.objects.get(
        entity_type=EventLog.EntityType.FEATURE,
        entity_id=body.id,
        event_type=EventLog.EventType.NEW,
    )
    assert event_log.event_details == {}


@pytest.mark.django_db
def test_create_feature_accepts_empty_parent_feature_id(project: Project) -> None:
    response = client.post(
        "/features",
        json={
            "project_id": project.id,
            "parent_feature_id": "",
            "name": "Password Reset",
            "description": "Allow users to reset forgotten passwords.",
        },
    )

    assert response.status_code == 200
    body = FeatureResponseSchema.model_validate(response.json())
    assert body.project_id == project.id
    assert body.parent_feature_id is None
    assert Feature.objects.get(id=body.id).parent_feature_id is None


@pytest.mark.django_db
def test_list_features(feature: Feature) -> None:
    response = client.get("/features")

    assert response.status_code == 200
    body = [FeatureResponseSchema.model_validate(item) for item in response.json()]
    assert len(body) == 2
    assert [item.id for item in body] == [feature.parent_feature_id, feature.id]


@pytest.mark.django_db
def test_get_feature(feature: Feature) -> None:
    response = client.get(f"/features/{feature.id}")

    assert response.status_code == 200
    body = FeatureResponseSchema.model_validate(response.json())
    assert body.id == feature.id
    assert body.project_id == feature.project_id
    assert body.parent_feature_id == feature.parent_feature_id


@pytest.mark.django_db
def test_update_feature(feature: Feature, other_project: Project) -> None:
    original_project_id = feature.project_id
    original_parent_feature_id = feature.parent_feature_id
    payload = FeatureUpdateSchema(
        project_id=other_project.id,
        parent_feature_id=None,
        name="SSO",
        description="Update the feature to support enterprise SSO.",
    )

    response = client.put(f"/features/{feature.id}", json=payload.model_dump())

    assert response.status_code == 200
    body = FeatureResponseSchema.model_validate(response.json())
    feature.refresh_from_db()
    assert body.project_id == other_project.id
    assert body.parent_feature_id is None
    assert feature.project_id == other_project.id
    assert feature.name == payload.name
    event_log = EventLog.objects.get(
        entity_type=EventLog.EntityType.FEATURE,
        entity_id=feature.id,
        event_type=EventLog.EventType.MODIFIED,
    )
    assert event_log.event_details == {
        "project_id": {"old": original_project_id, "new": other_project.id},
        "parent_feature_id": {"old": original_parent_feature_id, "new": None},
        "name": {"old": "OAuth Login", "new": payload.name},
        "description": {
            "old": "Allow sign in with external providers",
            "new": payload.description,
        },
    }


@pytest.mark.django_db
def test_update_feature_accepts_empty_parent_feature_id(feature: Feature) -> None:
    response = client.put(
        f"/features/{feature.id}",
        json={
            "project_id": feature.project_id,
            "parent_feature_id": "",
            "name": feature.name,
            "description": feature.description,
        },
    )

    assert response.status_code == 200
    body = FeatureResponseSchema.model_validate(response.json())
    feature.refresh_from_db()
    assert body.parent_feature_id is None
    assert feature.parent_feature_id is None


@pytest.mark.django_db
def test_delete_feature(feature: Feature) -> None:
    task = baker.make(
        Task,
        feature=feature,
        title="Feature task",
        description="Task removed with the feature",
        status="Todo",
    )
    child_feature = baker.make(
        Feature,
        project=feature.project,
        parent_feature=feature,
        name="Nested child",
        description="Becomes a root feature",
    )

    response = client.delete(f"/features/{feature.id}")

    assert response.status_code == 204
    assert not Feature.objects.filter(id=feature.id).exists()
    assert not Task.objects.filter(id=task.id).exists()
    child_feature.refresh_from_db()
    assert child_feature.parent_feature_id is None
    logged_events = list(
        EventLog.objects.order_by("id").values_list("entity_type", "entity_id", "event_type", "event_details")
    )
    assert logged_events == [
        (
            EventLog.EntityType.FEATURE,
            child_feature.id,
            EventLog.EventType.MODIFIED,
            {"parent_feature_id": {"old": feature.id, "new": None}},
        ),
        (EventLog.EntityType.TASK, task.id, EventLog.EventType.DELETED, {}),
        (EventLog.EntityType.FEATURE, feature.id, EventLog.EventType.DELETED, {}),
    ]


@pytest.mark.django_db
def test_create_feature_rejects_parent_from_different_project(
    project: Project,
    other_project: Project,
) -> None:
    parent_feature = baker.make(
        Feature,
        project=other_project,
        parent_feature=None,
        name="Foreign Parent",
        description="Belongs to another project",
    )
    payload = FeatureCreateSchema(
        project_id=project.id,
        parent_feature_id=parent_feature.id,
        name="Child",
        description="Should be rejected",
    )

    response = client.post("/features", json=payload.model_dump())

    assert response.status_code == 400
    assert response.json()["detail"] == "Parent feature must belong to the same project."


@pytest.mark.django_db
def test_update_feature_rejects_self_parent(feature: Feature) -> None:
    payload = FeatureUpdateSchema(
        project_id=feature.project_id,
        parent_feature_id=feature.id,
        name=feature.name,
        description=feature.description,
    )

    response = client.put(f"/features/{feature.id}", json=payload.model_dump())

    assert response.status_code == 400
    assert response.json()["detail"] == "A feature cannot be its own parent."


@pytest.mark.django_db
def test_update_feature_rejects_descendant_as_parent(
    project: Project,
    parent_feature: Feature,
) -> None:
    child_feature = baker.make(
        Feature,
        project=project,
        parent_feature=parent_feature,
        name="Child",
        description="Nested child",
    )
    grandchild_feature = baker.make(
        Feature,
        project=project,
        parent_feature=child_feature,
        name="Grandchild",
        description="Nested grandchild",
    )
    payload = FeatureUpdateSchema(
        project_id=project.id,
        parent_feature_id=grandchild_feature.id,
        name=parent_feature.name,
        description=parent_feature.description,
    )

    response = client.put(f"/features/{parent_feature.id}", json=payload.model_dump())

    assert response.status_code == 400
    assert response.json()["detail"] == "A feature cannot be assigned to its own descendant."
