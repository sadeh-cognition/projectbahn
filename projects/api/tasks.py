from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja.errors import HttpError
from ninja.responses import Status

from projects.api import api
from projects.api.common import (
    User,
    build_change_details,
    create_event_log,
    require_authenticated_user,
    serialize_task,
    tasks_queryset,
)
from projects.models import EventLog, Feature, Task, TaskUpdate
from projects.project_memory import (
    ProjectMemoryError,
    delete_task_memory,
    sync_task_memory,
)
from projects.schemas import (
    TaskCreateSchema,
    TaskResponseSchema,
    TaskUpdateCreateSchema,
    TaskUpdateEditSchema,
    TaskUpdateResponseSchema,
    TaskUpdateSchema,
)


def serialize_task_update(update: TaskUpdate) -> TaskUpdateResponseSchema:
    return TaskUpdateResponseSchema(
        id=update.id,
        task_id=update.task_id,
        user_id=update.user_id,
        user_username=update.user.get_username(),
        category=update.category,
        description=update.description,
        created_at=update.created_at,
        updated_at=update.updated_at,
    )


@api.get("/tasks", response=list[TaskResponseSchema])
def list_tasks(
    request: HttpRequest,
    project_id: int | None = None,
    feature_id: int | None = None,
    search: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    sort_by: str = "date_updated",
    sort_dir: str = "desc",
) -> list[TaskResponseSchema]:
    queryset = tasks_queryset()

    if project_id is not None:
        queryset = queryset.filter(feature__project_id=project_id)
    if feature_id is not None:
        queryset = queryset.filter(feature_id=feature_id)
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(feature__name__icontains=search)
            | Q(user__username__icontains=search)
        )
    if status:
        queryset = queryset.filter(status__icontains=status)
    if assignee:
        queryset = queryset.filter(user__username__icontains=assignee)

    sort_fields = {
        "title": "title",
        "status": "status",
        "feature": "feature__name",
        "assignee": "user__username",
        "date_created": "date_created",
        "date_updated": "date_updated",
    }
    order_field = sort_fields.get(sort_by, "date_updated")
    ordering_prefix = "" if sort_dir == "asc" else "-"
    tasks = queryset.order_by(f"{ordering_prefix}{order_field}", f"{ordering_prefix}id")
    return [serialize_task(task) for task in tasks]


@api.post("/tasks", response=TaskResponseSchema)
def create_task(
    request: HttpRequest,
    payload: TaskCreateSchema,
) -> TaskResponseSchema:
    feature = Feature.get_by_id_or_404(payload.feature_id)
    user = get_object_or_404(User, id=payload.user_id)
    with transaction.atomic():
        task = Task.create_task(
            feature=feature,
            user=user,
            title=payload.title,
            description=payload.description,
            status=payload.status,
        )
        create_event_log(
            entity_type=EventLog.EntityType.TASK,
            entity_id=task.id,
            event_type=EventLog.EventType.CREATED,
        )
        try:
            sync_task_memory(task=tasks_queryset().get(id=task.id))
        except ProjectMemoryError as exc:
            raise HttpError(503, str(exc)) from exc
    return serialize_task(tasks_queryset().get(id=task.id))


@api.get("/tasks/{task_id}", response=TaskResponseSchema)
def get_task(request: HttpRequest, task_id: int) -> TaskResponseSchema:
    task = Task.get_by_id_with_relations_or_404(task_id)
    return serialize_task(task)


@api.get("/tasks/{task_id}/updates", response=list[TaskUpdateResponseSchema])
def list_task_updates(
    request: HttpRequest,
    task_id: int,
) -> list[TaskUpdateResponseSchema]:
    Task.get_by_id_or_404(task_id)
    return [serialize_task_update(update) for update in TaskUpdate.get_for_task(task_id)]


@api.post("/tasks/{task_id}/updates", response=TaskUpdateResponseSchema)
def create_task_update(
    request: HttpRequest,
    task_id: int,
    payload: TaskUpdateCreateSchema,
) -> TaskUpdateResponseSchema:
    task = Task.get_by_id_or_404(task_id)
    update = TaskUpdate.create_update(
        task=task,
        user=require_authenticated_user(request),
        category=payload.category,
        description=payload.description,
    )
    return serialize_task_update(TaskUpdate.get_for_task(task_id).get(id=update.id))


@api.get(
    "/tasks/{task_id}/updates/{update_id}",
    response=TaskUpdateResponseSchema,
)
def get_task_update(
    request: HttpRequest,
    task_id: int,
    update_id: int,
) -> TaskUpdateResponseSchema:
    return serialize_task_update(
        TaskUpdate.get_for_task_or_404(task_id=task_id, update_id=update_id)
    )


@api.put(
    "/tasks/{task_id}/updates/{update_id}",
    response=TaskUpdateResponseSchema,
)
def edit_task_update(
    request: HttpRequest,
    task_id: int,
    update_id: int,
    payload: TaskUpdateEditSchema,
) -> TaskUpdateResponseSchema:
    update = TaskUpdate.get_for_task_or_404(task_id=task_id, update_id=update_id)
    update.category = payload.category
    update.description = payload.description
    update.save(update_fields=["category", "description", "updated_at"])
    update.refresh_from_db()
    return serialize_task_update(update)


@api.delete("/tasks/{task_id}/updates/{update_id}", response={204: None})
def delete_task_update(
    request: HttpRequest,
    task_id: int,
    update_id: int,
) -> Status[None]:
    update = TaskUpdate.get_for_task_or_404(task_id=task_id, update_id=update_id)
    update.delete()
    return Status(204, None)


@api.put("/tasks/{task_id}", response=TaskResponseSchema)
def update_task(
    request: HttpRequest,
    task_id: int,
    payload: TaskUpdateSchema,
) -> TaskResponseSchema:
    task = Task.get_by_id_or_404(task_id)
    feature = Feature.get_by_id_or_404(payload.feature_id)
    user = get_object_or_404(User, id=payload.user_id)
    updated_values = {
        "feature_id": feature.id,
        "user_id": user.id,
        "title": payload.title,
        "description": payload.description,
        "status": payload.status,
    }
    event_details = build_change_details(task, updated_values)
    old_status = task.status
    with transaction.atomic():
        task.feature = feature
        task.user = user
        task.title = payload.title
        task.description = payload.description
        task.status = payload.status
        task.save(
            update_fields=[
                "feature",
                "user",
                "title",
                "description",
                "status",
                "date_updated",
            ]
        )
        create_event_log(
            entity_type=EventLog.EntityType.TASK,
            entity_id=task.id,
            event_type=EventLog.EventType.MODIFIED,
            event_details=event_details,
        )
        if old_status != payload.status:
            TaskUpdate.create_update(
                task=task,
                user=require_authenticated_user(request),
                category="status",
                description=f'Status changed from "{old_status}" to "{payload.status}".',
            )
        try:
            sync_task_memory(task=tasks_queryset().get(id=task.id))
        except ProjectMemoryError as exc:
            raise HttpError(503, str(exc)) from exc
    return serialize_task(tasks_queryset().get(id=task.id))


@api.delete("/tasks/{task_id}", response={204: None})
def delete_task(request: HttpRequest, task_id: int) -> Status[None]:
    task = Task.get_by_id_with_relations_or_404(task_id)
    deleted_task_id = task.id
    with transaction.atomic():
        try:
            delete_task_memory(task=task)
        except ProjectMemoryError as exc:
            raise HttpError(503, str(exc)) from exc
        task.delete()
        create_event_log(
            entity_type=EventLog.EntityType.TASK,
            entity_id=deleted_task_id,
            event_type=EventLog.EventType.DELETED,
        )
    return Status(204, None)
