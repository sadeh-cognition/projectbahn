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
        EventLog.get_keys_for_event_type(EventLog.EventType.CREATED)
    )

    plans: list[EventLogBackfillPlan] = []
    entity_definitions = (
        (EventLog.EntityType.PROJECT, Project.get_all_ids_ordered_by_date()),
        (EventLog.EntityType.FEATURE, Feature.get_all_ids_ordered_by_date()),
        (EventLog.EntityType.TASK, Task.get_all_ids_ordered_by_date()),
    )
    for entity_type, entity_ids in entity_definitions:
        missing_ids = [entity_id for entity_id in entity_ids if (entity_type, entity_id) not in existing_created_event_keys]
        plans.append(EventLogBackfillPlan(entity_type=entity_type, entity_ids=missing_ids))
    return plans


def backfill_event_logs(*, dry_run: bool = False) -> EventLogBackfillResult:
    plans = _build_backfill_plans()
    created_count = sum(len(plan.entity_ids) for plan in plans)
    total_entity_count = Project.get_total_count() + Feature.get_total_count() + Task.get_total_count()
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
        EventLog.bulk_create_logs(event_logs)

    return EventLogBackfillResult(created_count=created_count, skipped_count=skipped_count)
