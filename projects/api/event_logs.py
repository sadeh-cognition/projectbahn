from __future__ import annotations

from django.http import HttpRequest
from ninja.errors import HttpError

from projects.api import api
from projects.api.common import serialize_event_log
from projects.models import EventLog
from projects.schemas import EventLogPageResponseSchema


@api.get("/event-logs", response=EventLogPageResponseSchema)
def list_event_logs(
    request: HttpRequest,
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> EventLogPageResponseSchema:
    if page < 1:
        raise HttpError(400, "Page must be greater than or equal to 1.")
    if page_size < 1:
        raise HttpError(400, "Page size must be greater than or equal to 1.")

    queryset = EventLog.get_base_queryset_ordered()

    if event_type is not None:
        queryset = queryset.filter(event_type=event_type)
    if entity_type is not None:
        queryset = queryset.filter(entity_type=entity_type)
    if entity_id is not None:
        queryset = queryset.filter(entity_id=entity_id)

    total = queryset.count()
    start = (page - 1) * page_size
    end = start + page_size
    items = [serialize_event_log(event_log) for event_log in queryset[start:end]]
    return EventLogPageResponseSchema(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
