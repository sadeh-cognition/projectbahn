from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from projects.models import EventLog, Feature, Project, Task


@dataclass(frozen=True)
class EventLogBackfillResult:
    created_count: int
    skipped_count: int


@dataclass(frozen=True)
class EventLogBackfillPlan:
    entity_type: EventLog.EntityType
    entity_ids: list[int]


def _build_backfill_plans() -> list[EventLogBackfillPlan]:
    existing_created_event_keys = set(
        EventLog.objects.filter(event_type=EventLog.EventType.CREATED).values_list("entity_type", "entity_id")
    )

    plans: list[EventLogBackfillPlan] = []
    entity_definitions = (
        (EventLog.EntityType.PROJECT, Project.objects.order_by("date_created", "id").values_list("id", flat=True)),
        (EventLog.EntityType.FEATURE, Feature.objects.order_by("date_created", "id").values_list("id", flat=True)),
        (EventLog.EntityType.TASK, Task.objects.order_by("date_created", "id").values_list("id", flat=True)),
    )
    for entity_type, entity_ids in entity_definitions:
        missing_ids = [entity_id for entity_id in entity_ids if (entity_type, entity_id) not in existing_created_event_keys]
        plans.append(EventLogBackfillPlan(entity_type=entity_type, entity_ids=missing_ids))
    return plans


def backfill_event_logs(*, dry_run: bool = False) -> EventLogBackfillResult:
    plans = _build_backfill_plans()
    created_count = sum(len(plan.entity_ids) for plan in plans)
    total_entity_count = Project.objects.count() + Feature.objects.count() + Task.objects.count()
    skipped_count = total_entity_count - created_count

    if dry_run or created_count == 0:
        return EventLogBackfillResult(created_count=created_count, skipped_count=skipped_count)

    event_logs = [
        EventLog(
            entity_type=plan.entity_type,
            entity_id=entity_id,
            event_type=EventLog.EventType.CREATED,
            event_details={},
        )
        for plan in plans
        for entity_id in plan.entity_ids
    ]
    with transaction.atomic():
        EventLog.objects.bulk_create(event_logs)

    return EventLogBackfillResult(created_count=created_count, skipped_count=skipped_count)
