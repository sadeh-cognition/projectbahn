from __future__ import annotations

from django.db import transaction
from django.http import HttpRequest
from ninja.errors import HttpError
from ninja.responses import Status

from projects.api import api
from projects.api.common import (
    build_change_details,
    build_deleted_event_log,
    create_event_log,
    serialize_feature,
    tasks_queryset,
)
from projects.models import EventLog, Feature, Project, Task
from projects.project_memory import (
    ProjectMemoryError,
    delete_feature_memory,
    delete_task_memory,
    sync_feature_memory,
)
from projects.schemas import (
    FeatureCreateSchema,
    FeatureResponseSchema,
    FeatureUpdateSchema,
)
from projects.services.parent import validate_parent_feature


@api.get("/features", response=list[FeatureResponseSchema])
def list_features(request: HttpRequest) -> list[FeatureResponseSchema]:
    return [
        serialize_feature(feature)
        for feature in Feature.get_all_with_relations_ordered()
    ]


@api.post("/features", response=FeatureResponseSchema)
def create_feature(
    request: HttpRequest,
    payload: FeatureCreateSchema,
) -> FeatureResponseSchema:
    project = Project.get_by_id_or_404(payload.project_id)
    parent_feature = (
        Feature.get_by_id_or_404(payload.parent_feature_id)
        if payload.parent_feature_id
        else None
    )
    validate_parent_feature(project=project, parent_feature=parent_feature)
    with transaction.atomic():
        feature = Feature.create_feature(
            project=project,
            parent_feature=parent_feature,
            name=payload.name,
            description=payload.description,
        )
        create_event_log(
            entity_type=EventLog.EntityType.FEATURE,
            entity_id=feature.id,
            event_type=EventLog.EventType.CREATED,
        )
        try:
            sync_feature_memory(feature=feature)
        except ProjectMemoryError as exc:
            raise HttpError(503, str(exc)) from exc
    return serialize_feature(feature)


@api.get("/features/{feature_id}", response=FeatureResponseSchema)
def get_feature(request: HttpRequest, feature_id: int) -> FeatureResponseSchema:
    return serialize_feature(Feature.get_by_id_with_relations_or_404(feature_id))


@api.put("/features/{feature_id}", response=FeatureResponseSchema)
def update_feature(
    request: HttpRequest,
    feature_id: int,
    payload: FeatureUpdateSchema,
) -> FeatureResponseSchema:
    feature = Feature.get_by_id_or_404(feature_id)
    project = Project.get_by_id_or_404(payload.project_id)
    parent_feature = (
        Feature.get_by_id_or_404(payload.parent_feature_id)
        if payload.parent_feature_id
        else None
    )
    validate_parent_feature(
        project=project, parent_feature=parent_feature, feature_id=feature_id
    )
    updated_values = {
        "project_id": project.id,
        "parent_feature_id": parent_feature.id if parent_feature is not None else None,
        "name": payload.name,
        "description": payload.description,
    }
    event_details = build_change_details(feature, updated_values)
    with transaction.atomic():
        feature.project = project
        feature.parent_feature = parent_feature
        feature.name = payload.name
        feature.description = payload.description
        feature.save(
            update_fields=[
                "project",
                "parent_feature",
                "name",
                "description",
                "date_updated",
            ]
        )
        create_event_log(
            entity_type=EventLog.EntityType.FEATURE,
            entity_id=feature.id,
            event_type=EventLog.EventType.MODIFIED,
            event_details=event_details,
        )
        try:
            sync_feature_memory(feature=feature)
        except ProjectMemoryError as exc:
            raise HttpError(503, str(exc)) from exc
    return serialize_feature(feature)


@api.delete("/features/{feature_id}", response={204: None})
def delete_feature(request: HttpRequest, feature_id: int) -> Status[None]:
    feature = Feature.get_by_id_or_404(feature_id)
    deleted_feature_id = feature.id
    tasks_to_delete = list(tasks_queryset().filter(feature_id=deleted_feature_id))
    task_ids = list(Task.get_ids_for_feature(deleted_feature_id))
    child_features = list(
        Feature.get_features_for_project_with_relations(feature.project_id).filter(
            parent_feature_id=deleted_feature_id
        )
    )
    child_feature_ids = [child_feature.id for child_feature in child_features]
    with transaction.atomic():
        try:
            for task in tasks_to_delete:
                delete_task_memory(task=task)
            delete_feature_memory(feature=feature)
        except ProjectMemoryError as exc:
            raise HttpError(503, str(exc)) from exc
        feature.delete()
        try:
            for child_feature_id in child_feature_ids:
                sync_feature_memory(
                    feature=Feature.get_by_id_with_project_or_404(child_feature_id)
                )
        except ProjectMemoryError as exc:
            raise HttpError(503, str(exc)) from exc
        EventLog.bulk_create_logs(
            [
                *[
                    EventLog(
                        entity_type=EventLog.EntityType.FEATURE,
                        entity_id=child_feature_id,
                        event_type=EventLog.EventType.MODIFIED,
                        event_details={
                            "parent_feature_id": {
                                "old": deleted_feature_id,
                                "new": None,
                            }
                        },
                    )
                    for child_feature_id in child_feature_ids
                ],
                *[
                    build_deleted_event_log(EventLog.EntityType.TASK, task_id)
                    for task_id in task_ids
                ],
                build_deleted_event_log(
                    EventLog.EntityType.FEATURE, deleted_feature_id
                ),
            ]
        )
    return Status(204, None)
