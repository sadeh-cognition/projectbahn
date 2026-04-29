from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.http import HttpRequest
from ninja.errors import HttpError

from projects.models import EventLog, Feature, Project, Task
from projects.schemas import (
    EventLogResponseSchema,
    FeatureResponseSchema,
    ProjectCodebaseAgentConfigResponseSchema,
    ProjectLLMConfigResponseSchema,
    ProjectResponseSchema,
    TaskResponseSchema,
)

User = get_user_model()


def serialize_task(task: Task) -> TaskResponseSchema:
    return TaskResponseSchema(
        id=task.id,
        entity_type=EventLog.EntityType.TASK,
        project_id=task.feature.project_id,
        project_name=task.feature.project.name,
        feature_id=task.feature_id,
        feature_name=task.feature.name,
        user_id=task.user_id,
        user_username=task.user.get_username(),
        title=task.title,
        description=task.description,
        status=task.status,
        date_created=task.date_created,
        date_updated=task.date_updated,
    )


def tasks_queryset() -> QuerySet[Task]:
    return Task.get_base_queryset_with_relations()


def serialize_project(project: Project) -> ProjectResponseSchema:
    return ProjectResponseSchema(
        id=project.id,
        entity_type=EventLog.EntityType.PROJECT,
        name=project.name,
        description=project.description,
        date_created=project.date_created,
        date_updated=project.date_updated,
    )


def serialize_project_llm_config(project: Project) -> ProjectLLMConfigResponseSchema:
    try:
        config = project.llm_config
    except ObjectDoesNotExist:
        return ProjectLLMConfigResponseSchema(
            project_id=project.id,
            provider="",
            llm_name="",
            api_key_configured=False,
            api_key_usable=False,
            api_key_requires_reentry=False,
            date_created=project.date_created,
            date_updated=project.date_updated,
        )

    return ProjectLLMConfigResponseSchema(
        project_id=project.id,
        provider=config.provider,
        llm_name=config.llm_name,
        api_key_configured=config.api_key_configured,
        api_key_usable=config.api_key_usable,
        api_key_requires_reentry=config.api_key_requires_reentry,
        date_created=config.date_created,
        date_updated=config.date_updated,
    )


def serialize_project_codebase_agent_config(
    project: Project,
) -> ProjectCodebaseAgentConfigResponseSchema:
    try:
        config = project.codebase_agent_config
    except ObjectDoesNotExist:
        return ProjectCodebaseAgentConfigResponseSchema(
            project_id=project.id,
            url="",
            date_created=project.date_created,
            date_updated=project.date_updated,
        )

    return ProjectCodebaseAgentConfigResponseSchema(
        project_id=project.id,
        url=config.url,
        date_created=config.date_created,
        date_updated=config.date_updated,
    )


def serialize_feature(feature: Feature) -> FeatureResponseSchema:
    return FeatureResponseSchema(
        id=feature.id,
        entity_type=EventLog.EntityType.FEATURE,
        project_id=feature.project_id,
        parent_feature_id=feature.parent_feature_id,
        name=feature.name,
        description=feature.description,
        date_created=feature.date_created,
        date_updated=feature.date_updated,
    )


def serialize_event_log(event_log: EventLog) -> EventLogResponseSchema:
    return EventLogResponseSchema(
        id=event_log.id,
        entity_type=event_log.entity_type,
        entity_id=event_log.entity_id,
        event_type=event_log.event_type,
        event_details=event_log.event_details,
    )


def build_change_details(
    instance: Project | Feature | Task,
    updated_values: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for field_name, new_value in updated_values.items():
        old_value = getattr(instance, field_name)
        if old_value != new_value:
            changes[field_name] = {"old": old_value, "new": new_value}
    return changes


def create_event_log(
    *,
    entity_type: EventLog.EntityType,
    entity_id: int,
    event_type: EventLog.EventType,
    event_details: dict[str, Any] | None = None,
) -> EventLog:
    return EventLog.create_log(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        event_details=event_details or {},
    )


def build_deleted_event_log(
    entity_type: EventLog.EntityType, entity_id: int
) -> EventLog:
    return EventLog(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=EventLog.EventType.DELETED,
        event_details={},
    )


def require_authenticated_user(request: HttpRequest) -> User:
    if not request.user.is_authenticated:
        raise HttpError(401, "Authentication required.")
    return request.user


async def arequire_authenticated_user(request: HttpRequest) -> User:
    if not (await request.auser()).is_authenticated:
        raise HttpError(401, "Authentication required.")
    return request.user
