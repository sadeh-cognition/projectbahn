from __future__ import annotations

from django.core.management import call_command

import pytest
from model_bakery import baker

from projects.models import EventLog, Feature, Project, Task


@pytest.mark.django_db
def test_backfill_event_logs_creates_missing_created_events(django_user_model, capsys) -> None:
    user = baker.make(django_user_model)
    project = baker.make(Project)
    feature = baker.make(Feature, project=project, parent_feature=None)
    task = baker.make(Task, feature=feature, user=user)
    existing_project_event = baker.make(
        EventLog,
        entity_type=EventLog.EntityType.PROJECT,
        entity_id=project.id,
        event_type=EventLog.EventType.CREATED,
        event_details={},
    )

    call_command("backfill_event_logs")

    captured = capsys.readouterr()
    assert captured.out.strip() == "Created 2 event logs; skipped 1 entities with existing logs."
    created_events = list(
        EventLog.objects.order_by("id").values_list("entity_type", "entity_id", "event_type", "event_details")
    )
    assert created_events == [
        (
            EventLog.EntityType.PROJECT,
            project.id,
            EventLog.EventType.CREATED,
            {},
        ),
        (
            EventLog.EntityType.FEATURE,
            feature.id,
            EventLog.EventType.CREATED,
            {},
        ),
        (
            EventLog.EntityType.TASK,
            task.id,
            EventLog.EventType.CREATED,
            {},
        ),
    ]
    assert EventLog.objects.get(id=existing_project_event.id).event_type == EventLog.EventType.CREATED


@pytest.mark.django_db
def test_backfill_event_logs_is_dry_run(django_user_model, capsys) -> None:
    user = baker.make(django_user_model)
    project = baker.make(Project)
    feature = baker.make(Feature, project=project, parent_feature=None)
    baker.make(Task, feature=feature, user=user)

    call_command("backfill_event_logs", "--dry-run")

    captured = capsys.readouterr()
    assert captured.out.strip() == "Would create 3 event logs; skipped 0 entities with existing logs."
    assert EventLog.objects.count() == 0
