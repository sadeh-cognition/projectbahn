from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

import pytest
from model_bakery import baker

from projects.models import EventLog, Feature, Project, Task

User = get_user_model()


@pytest.fixture
def admin_client() -> Client:
    client = Client()
    admin_user = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="password123",
    )
    client.force_login(admin_user)
    return client


@pytest.fixture
def admin_records() -> None:
    project = baker.make(Project, name="Platform", description="Core platform")
    feature = baker.make(
        Feature,
        project=project,
        parent_feature=None,
        name="Authentication",
        description="Authentication work",
    )
    task = baker.make(
        Task,
        feature=feature,
        title="Ship login",
        description="Build login flow",
        status="In progress",
    )
    baker.make(
        EventLog,
        entity_type=EventLog.EntityType.TASK,
        entity_id=task.id,
        event_type=EventLog.EventType.NEW,
        event_details={"title": task.title},
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url_name", "expected_text"),
    [
        ("admin:projects_project_changelist", "Platform"),
        ("admin:projects_feature_changelist", "Authentication"),
        ("admin:projects_task_changelist", "Ship login"),
        ("admin:projects_eventlog_changelist", "Task"),
    ],
)
def test_project_model_admin_changelists_render(
    admin_client: Client,
    admin_records: None,
    url_name: str,
    expected_text: str,
) -> None:
    response = admin_client.get(reverse(url_name))

    assert response.status_code == 200
    assert expected_text in response.content.decode("utf-8")
