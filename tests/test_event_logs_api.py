from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

from django.utils import timezone
from tests.api_client import AuthenticatedTestClient as TestClient

import pytest
from model_bakery import baker

from projects.api import api
from projects.models import EventLog
from projects.schemas import EventLogPageResponseSchema

client = TestClient(api)


@pytest.mark.django_db
def test_list_event_logs_supports_pagination() -> None:
    baker.make(
        EventLog,
        entity_type=EventLog.EntityType.PROJECT,
        entity_id=1,
        event_type=EventLog.EventType.CREATED,
        event_details={"name": "Alpha"},
    )
    second_log = baker.make(
        EventLog,
        entity_type=EventLog.EntityType.FEATURE,
        entity_id=2,
        event_type=EventLog.EventType.MODIFIED,
        event_details={"name": {"old": "Old", "new": "New"}},
    )
    third_log = baker.make(
        EventLog,
        entity_type=EventLog.EntityType.TASK,
        entity_id=3,
        event_type=EventLog.EventType.DELETED,
        event_details={},
    )

    response = client.get("/event-logs?page=1&page_size=2")

    assert response.status_code == 200
    body = EventLogPageResponseSchema.model_validate(response.json())
    assert body.total == 3
    assert body.page == 1
    assert body.page_size == 2
    assert [item.id for item in body.items] == [third_log.id, second_log.id]
    assert body.items[0].event_type == third_log.event_type
    assert body.items[1].event_type == second_log.event_type


@pytest.mark.django_db
def test_list_event_logs_filters_by_event_and_entity_fields() -> None:
    target_log = baker.make(
        EventLog,
        entity_type=EventLog.EntityType.TASK,
        entity_id=42,
        event_type=EventLog.EventType.MODIFIED,
        event_details={"status": {"old": "Todo", "new": "Done"}},
    )
    baker.make(
        EventLog,
        entity_type=EventLog.EntityType.TASK,
        entity_id=42,
        event_type=EventLog.EventType.CREATED,
        event_details={},
    )
    baker.make(
        EventLog,
        entity_type=EventLog.EntityType.FEATURE,
        entity_id=42,
        event_type=EventLog.EventType.MODIFIED,
        event_details={},
    )
    baker.make(
        EventLog,
        entity_type=EventLog.EntityType.TASK,
        entity_id=99,
        event_type=EventLog.EventType.MODIFIED,
        event_details={},
    )

    response = client.get(
        (
            f"/event-logs?event_type={EventLog.EventType.MODIFIED}"
            f"&entity_type={EventLog.EntityType.TASK}"
            f"&entity_id={target_log.entity_id}"
        )
    )

    assert response.status_code == 200
    body = EventLogPageResponseSchema.model_validate(response.json())
    assert body.total == 1
    assert body.page == 1
    assert body.page_size == 50
    assert len(body.items) == 1
    assert body.items[0].id == target_log.id
    assert body.items[0].event_details == target_log.event_details


@pytest.mark.django_db
def test_list_event_logs_filters_after_id() -> None:
    first_log = baker.make(EventLog)
    second_log = baker.make(EventLog)
    third_log = baker.make(EventLog)

    response = client.get(f"/event-logs?after_id={first_log.id}")

    assert response.status_code == 200
    body = EventLogPageResponseSchema.model_validate(response.json())
    assert [item.id for item in body.items] == [third_log.id, second_log.id]
    assert all(item.created_at is not None for item in body.items)


@pytest.mark.django_db
def test_list_event_logs_filters_after_time() -> None:
    older_log = baker.make(EventLog)
    newer_log = baker.make(EventLog)
    cutoff = timezone.now()
    EventLog.objects.filter(id=older_log.id).update(
        created_at=cutoff - timedelta(seconds=1)
    )
    EventLog.objects.filter(id=newer_log.id).update(
        created_at=cutoff + timedelta(seconds=1)
    )

    query = urlencode({"after_time": cutoff.isoformat()})
    response = client.get(f"/event-logs?{query}")

    assert response.status_code == 200
    body = EventLogPageResponseSchema.model_validate(response.json())
    assert [item.id for item in body.items] == [newer_log.id]


@pytest.mark.django_db
def test_list_event_logs_rejects_invalid_pagination_parameters() -> None:
    response = client.get("/event-logs?page=0&page_size=10")

    assert response.status_code == 400
    assert response.json()["detail"] == "Page must be greater than or equal to 1."
