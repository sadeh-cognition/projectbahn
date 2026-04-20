from __future__ import annotations

import json
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import HttpRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.db.models import Q, QuerySet
from ninja.errors import HttpError
from ninja import NinjaAPI
from ninja.responses import Status

from projects.feature_chat import (
    FeatureChatConfigurationError,
    create_feature_chat_thread,
    generate_feature_chat_reply,
    serialize_message,
    serialize_thread,
)
from projects.models import EventLog, Feature, FeatureChatThread, Project, ProjectLLMConfig, Task
from projects.schemas import (
    EventLogPageResponseSchema,
    FeatureChatStreamRequestSchema,
    FeatureChatThreadCreateSchema,
    FeatureChatThreadDetailSchema,
    FeatureChatThreadResponseSchema,
    EventLogResponseSchema,
    FeatureCreateSchema,
    FeatureResponseSchema,
    FeatureUpdateSchema,
    ProjectCreateSchema,
    ProjectLLMConfigResponseSchema,
    ProjectLLMConfigUpdateSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
    TaskCreateSchema,
    TaskResponseSchema,
    TaskUpdateSchema,
    UserResponseSchema,
)

api = NinjaAPI()
User = get_user_model()


def _get_parent_feature(parent_feature_id: int | None) -> Feature | None:
    if parent_feature_id is None:
        return None
    return get_object_or_404(Feature, id=parent_feature_id)


def _validate_parent_feature(
    *,
    project: Project,
    parent_feature: Feature | None,
    feature_id: int | None = None,
) -> None:
    if parent_feature is None:
        return
    if feature_id is not None and parent_feature.id == feature_id:
        raise HttpError(400, "A feature cannot be its own parent.")
    if parent_feature.project_id != project.id:
        raise HttpError(400, "Parent feature must belong to the same project.")
    if feature_id is not None:
        ancestor = parent_feature
        while ancestor is not None:
            if ancestor.id == feature_id:
                raise HttpError(400, "A feature cannot be assigned to its own descendant.")
            ancestor = ancestor.parent_feature


def _serialize_task(task: Task) -> TaskResponseSchema:
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


def _tasks_queryset() -> QuerySet[Task]:
    return Task.objects.select_related("feature__project", "user")


def _serialize_project(project: Project) -> ProjectResponseSchema:
    return ProjectResponseSchema(
        id=project.id,
        entity_type=EventLog.EntityType.PROJECT,
        name=project.name,
        description=project.description,
        date_created=project.date_created,
        date_updated=project.date_updated,
    )


def _serialize_project_llm_config(project: Project) -> ProjectLLMConfigResponseSchema:
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


def _serialize_feature(feature: Feature) -> FeatureResponseSchema:
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


def _serialize_event_log(event_log: EventLog) -> EventLogResponseSchema:
    return EventLogResponseSchema(
        id=event_log.id,
        entity_type=event_log.entity_type,
        entity_id=event_log.entity_id,
        event_type=event_log.event_type,
        event_details=event_log.event_details,
    )


def _build_change_details(
    instance: Project | Feature | Task,
    updated_values: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for field_name, new_value in updated_values.items():
        old_value = getattr(instance, field_name)
        if old_value != new_value:
            changes[field_name] = {"old": old_value, "new": new_value}
    return changes


def _create_event_log(
    *,
    entity_type: EventLog.EntityType,
    entity_id: int,
    event_type: EventLog.EventType,
    event_details: dict[str, Any] | None = None,
) -> EventLog:
    return EventLog.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        event_details=event_details or {},
    )


def _build_deleted_event_log(entity_type: EventLog.EntityType, entity_id: int) -> EventLog:
    return EventLog(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=EventLog.EventType.DELETED,
        event_details={},
    )


def _require_authenticated_user(request: HttpRequest) -> User:
    if not request.user.is_authenticated:
        raise HttpError(401, "Authentication required.")
    return request.user


def _get_feature_chat_thread(*, feature_id: int, thread_id: int, user: User) -> FeatureChatThread:
    return get_object_or_404(
        FeatureChatThread.objects.select_related("feature__project", "owner", "chat"),
        id=thread_id,
        feature_id=feature_id,
        owner_id=user.id,
    )


def _iter_text_chunks(text: str, *, chunk_size: int = 48) -> list[str]:
    chunks: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > chunk_size:
            chunks.append(f"{current} ")
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    if not chunks:
        return [text]
    return chunks


@api.get("/users", response=list[UserResponseSchema])
def list_users(request: HttpRequest) -> list[User]:
    return list(User.objects.order_by("username", "id"))


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

    queryset = EventLog.objects.order_by("-id")

    if event_type is not None:
        queryset = queryset.filter(event_type=event_type)
    if entity_type is not None:
        queryset = queryset.filter(entity_type=entity_type)
    if entity_id is not None:
        queryset = queryset.filter(entity_id=entity_id)

    total = queryset.count()
    start = (page - 1) * page_size
    end = start + page_size
    items = [_serialize_event_log(event_log) for event_log in queryset[start:end]]
    return EventLogPageResponseSchema(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@api.get("/projects", response=list[ProjectResponseSchema])
def list_projects(request: HttpRequest) -> list[ProjectResponseSchema]:
    return [_serialize_project(project) for project in Project.objects.order_by("id")]


@api.post("/projects", response=ProjectResponseSchema)
def create_project(
    request: HttpRequest,
    payload: ProjectCreateSchema,
) -> ProjectResponseSchema:
    with transaction.atomic():
        project = Project.objects.create(
            name=payload.name,
            description=payload.description,
        )
        _create_event_log(
            entity_type=EventLog.EntityType.PROJECT,
            entity_id=project.id,
            event_type=EventLog.EventType.CREATED,
        )
    return _serialize_project(project)


@api.get("/projects/{project_id}", response=ProjectResponseSchema)
def get_project(request: HttpRequest, project_id: int) -> ProjectResponseSchema:
    return _serialize_project(get_object_or_404(Project, id=project_id))


@api.get("/projects/{project_id}/llm-config", response=ProjectLLMConfigResponseSchema)
def get_project_llm_config(request: HttpRequest, project_id: int) -> ProjectLLMConfigResponseSchema:
    project = get_object_or_404(Project, id=project_id)
    return _serialize_project_llm_config(project)


@api.put("/projects/{project_id}", response=ProjectResponseSchema)
def update_project(
    request: HttpRequest,
    project_id: int,
    payload: ProjectUpdateSchema,
) -> ProjectResponseSchema:
    project = get_object_or_404(Project, id=project_id)
    updated_values = {
        "name": payload.name,
        "description": payload.description,
    }
    event_details = _build_change_details(project, updated_values)
    with transaction.atomic():
        project.name = payload.name
        project.description = payload.description
        project.save(update_fields=["name", "description", "date_updated"])
        _create_event_log(
            entity_type=EventLog.EntityType.PROJECT,
            entity_id=project.id,
            event_type=EventLog.EventType.MODIFIED,
            event_details=event_details,
        )
    return _serialize_project(project)


@api.put("/projects/{project_id}/llm-config", response=ProjectLLMConfigResponseSchema)
def update_project_llm_config(
    request: HttpRequest,
    project_id: int,
    payload: ProjectLLMConfigUpdateSchema,
) -> ProjectLLMConfigResponseSchema:
    project = get_object_or_404(Project, id=project_id)
    with transaction.atomic():
        config, _ = ProjectLLMConfig.objects.get_or_create(project=project)
        config.provider = payload.provider
        config.llm_name = payload.llm_name
        if payload.api_key:
            config.set_api_key(payload.api_key)
            config.save(
                update_fields=["provider", "llm_name", "api_key_hash", "encrypted_api_key", "date_updated"]
            )
        else:
            config.save(update_fields=["provider", "llm_name", "date_updated"])
    return _serialize_project_llm_config(project)


@api.delete("/projects/{project_id}", response={204: None})
def delete_project(request: HttpRequest, project_id: int) -> Status[None]:
    project = get_object_or_404(Project, id=project_id)
    deleted_project_id = project.id
    feature_ids = list(
        Feature.objects.filter(project_id=deleted_project_id).order_by("id").values_list("id", flat=True)
    )
    task_ids = list(
        Task.objects.filter(feature__project_id=deleted_project_id).order_by("id").values_list("id", flat=True)
    )
    with transaction.atomic():
        project.delete()
        EventLog.objects.bulk_create(
            [
                *[_build_deleted_event_log(EventLog.EntityType.TASK, task_id) for task_id in task_ids],
                *[_build_deleted_event_log(EventLog.EntityType.FEATURE, feature_id) for feature_id in feature_ids],
                _build_deleted_event_log(EventLog.EntityType.PROJECT, deleted_project_id),
            ]
        )
    return Status(204, None)


@api.get("/features", response=list[FeatureResponseSchema])
def list_features(request: HttpRequest) -> list[FeatureResponseSchema]:
    return [
        _serialize_feature(feature)
        for feature in Feature.objects.select_related("project", "parent_feature").order_by("id")
    ]


@api.post("/features", response=FeatureResponseSchema)
def create_feature(
    request: HttpRequest,
    payload: FeatureCreateSchema,
) -> FeatureResponseSchema:
    project = get_object_or_404(Project, id=payload.project_id)
    parent_feature = _get_parent_feature(payload.parent_feature_id)
    _validate_parent_feature(project=project, parent_feature=parent_feature)
    with transaction.atomic():
        feature = Feature.objects.create(
            project=project,
            parent_feature=parent_feature,
            name=payload.name,
            description=payload.description,
        )
        _create_event_log(
            entity_type=EventLog.EntityType.FEATURE,
            entity_id=feature.id,
            event_type=EventLog.EventType.CREATED,
        )
    return _serialize_feature(feature)


@api.get("/features/{feature_id}", response=FeatureResponseSchema)
def get_feature(request: HttpRequest, feature_id: int) -> FeatureResponseSchema:
    return _serialize_feature(
        get_object_or_404(Feature.objects.select_related("project", "parent_feature"), id=feature_id)
    )


@api.put("/features/{feature_id}", response=FeatureResponseSchema)
def update_feature(
    request: HttpRequest,
    feature_id: int,
    payload: FeatureUpdateSchema,
) -> FeatureResponseSchema:
    feature = get_object_or_404(Feature, id=feature_id)
    project = get_object_or_404(Project, id=payload.project_id)
    parent_feature = _get_parent_feature(payload.parent_feature_id)
    _validate_parent_feature(project=project, parent_feature=parent_feature, feature_id=feature_id)
    updated_values = {
        "project_id": project.id,
        "parent_feature_id": parent_feature.id if parent_feature is not None else None,
        "name": payload.name,
        "description": payload.description,
    }
    event_details = _build_change_details(feature, updated_values)
    with transaction.atomic():
        feature.project = project
        feature.parent_feature = parent_feature
        feature.name = payload.name
        feature.description = payload.description
        feature.save(update_fields=["project", "parent_feature", "name", "description", "date_updated"])
        _create_event_log(
            entity_type=EventLog.EntityType.FEATURE,
            entity_id=feature.id,
            event_type=EventLog.EventType.MODIFIED,
            event_details=event_details,
        )
    return _serialize_feature(feature)


@api.delete("/features/{feature_id}", response={204: None})
def delete_feature(request: HttpRequest, feature_id: int) -> Status[None]:
    feature = get_object_or_404(Feature, id=feature_id)
    deleted_feature_id = feature.id
    task_ids = list(Task.objects.filter(feature_id=deleted_feature_id).order_by("id").values_list("id", flat=True))
    child_feature_ids = list(
        Feature.objects.filter(parent_feature_id=deleted_feature_id).order_by("id").values_list("id", flat=True)
    )
    with transaction.atomic():
        feature.delete()
        EventLog.objects.bulk_create(
            [
                *[
                    EventLog(
                        entity_type=EventLog.EntityType.FEATURE,
                        entity_id=child_feature_id,
                        event_type=EventLog.EventType.MODIFIED,
                        event_details={"parent_feature_id": {"old": deleted_feature_id, "new": None}},
                    )
                    for child_feature_id in child_feature_ids
                ],
                *[_build_deleted_event_log(EventLog.EntityType.TASK, task_id) for task_id in task_ids],
                _build_deleted_event_log(EventLog.EntityType.FEATURE, deleted_feature_id),
            ]
        )
    return Status(204, None)


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
    queryset = _tasks_queryset()

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
    return [_serialize_task(task) for task in tasks]


@api.post("/tasks", response=TaskResponseSchema)
def create_task(
    request: HttpRequest,
    payload: TaskCreateSchema,
) -> TaskResponseSchema:
    feature = get_object_or_404(Feature, id=payload.feature_id)
    user = get_object_or_404(User, id=payload.user_id)
    with transaction.atomic():
        task = Task.objects.create(
            feature=feature,
            user=user,
            title=payload.title,
            description=payload.description,
            status=payload.status,
        )
        _create_event_log(
            entity_type=EventLog.EntityType.TASK,
            entity_id=task.id,
            event_type=EventLog.EventType.CREATED,
        )
    return _serialize_task(_tasks_queryset().get(id=task.id))


@api.get("/tasks/{task_id}", response=TaskResponseSchema)
def get_task(request: HttpRequest, task_id: int) -> TaskResponseSchema:
    task = get_object_or_404(_tasks_queryset(), id=task_id)
    return _serialize_task(task)


@api.put("/tasks/{task_id}", response=TaskResponseSchema)
def update_task(
    request: HttpRequest,
    task_id: int,
    payload: TaskUpdateSchema,
) -> TaskResponseSchema:
    task = get_object_or_404(Task, id=task_id)
    feature = get_object_or_404(Feature, id=payload.feature_id)
    user = get_object_or_404(User, id=payload.user_id)
    updated_values = {
        "feature_id": feature.id,
        "user_id": user.id,
        "title": payload.title,
        "description": payload.description,
        "status": payload.status,
    }
    event_details = _build_change_details(task, updated_values)
    with transaction.atomic():
        task.feature = feature
        task.user = user
        task.title = payload.title
        task.description = payload.description
        task.status = payload.status
        task.save(update_fields=["feature", "user", "title", "description", "status", "date_updated"])
        _create_event_log(
            entity_type=EventLog.EntityType.TASK,
            entity_id=task.id,
            event_type=EventLog.EventType.MODIFIED,
            event_details=event_details,
        )
    return _serialize_task(_tasks_queryset().get(id=task.id))


@api.delete("/tasks/{task_id}", response={204: None})
def delete_task(request: HttpRequest, task_id: int) -> Status[None]:
    task = get_object_or_404(Task, id=task_id)
    deleted_task_id = task.id
    with transaction.atomic():
        task.delete()
        _create_event_log(
            entity_type=EventLog.EntityType.TASK,
            entity_id=deleted_task_id,
            event_type=EventLog.EventType.DELETED,
        )
    return Status(204, None)


@api.get("/features/{feature_id}/chat-threads", response=list[FeatureChatThreadResponseSchema])
def list_feature_chat_threads(request: HttpRequest, feature_id: int) -> list[FeatureChatThreadResponseSchema]:
    user = _require_authenticated_user(request)
    get_object_or_404(Feature, id=feature_id)
    threads = FeatureChatThread.objects.select_related("owner").filter(feature_id=feature_id, owner_id=user.id)
    return [FeatureChatThreadResponseSchema.model_validate(serialize_thread(thread)) for thread in threads]


@api.post("/features/{feature_id}/chat-threads", response=FeatureChatThreadResponseSchema)
def create_feature_thread(
    request: HttpRequest,
    feature_id: int,
    payload: FeatureChatThreadCreateSchema,
) -> FeatureChatThreadResponseSchema:
    user = _require_authenticated_user(request)
    feature = get_object_or_404(Feature.objects.select_related("project"), id=feature_id)
    try:
        thread = create_feature_chat_thread(feature=feature, user=user, title=payload.title)
    except FeatureChatConfigurationError as exc:
        raise HttpError(400, str(exc)) from exc
    return FeatureChatThreadResponseSchema.model_validate(serialize_thread(thread))


@api.get("/features/{feature_id}/chat-threads/{thread_id}", response=FeatureChatThreadDetailSchema)
def get_feature_chat_thread(request: HttpRequest, feature_id: int, thread_id: int) -> FeatureChatThreadDetailSchema:
    user = _require_authenticated_user(request)
    thread = _get_feature_chat_thread(feature_id=feature_id, thread_id=thread_id, user=user)
    return FeatureChatThreadDetailSchema(
        thread=FeatureChatThreadResponseSchema.model_validate(serialize_thread(thread)),
        messages=[serialize_message(message) for message in thread.messages.order_by("date_created", "id")],
    )


@api.post("/features/{feature_id}/chat-threads/{thread_id}/messages/stream")
def stream_feature_chat_message(
    request: HttpRequest,
    feature_id: int,
    thread_id: int,
    payload: FeatureChatStreamRequestSchema,
) -> StreamingHttpResponse:
    user = _require_authenticated_user(request)
    thread = _get_feature_chat_thread(feature_id=feature_id, thread_id=thread_id, user=user)
    try:
        reply = generate_feature_chat_reply(thread=thread, text=payload.text, user=user)
    except FeatureChatConfigurationError as exc:
        raise HttpError(400, str(exc)) from exc

    def event_stream() -> Any:
        for chunk in _iter_text_chunks(reply.assistant_message.text):
            yield json.dumps({"type": "chunk", "text": chunk}) + "\n"
        yield json.dumps(
            {
                "type": "done",
                "assistant_message": serialize_message(reply.assistant_message),
                "thread": serialize_thread(thread),
                "llm_call_id": reply.llm_call_id,
            }
        ) + "\n"

    return StreamingHttpResponse(event_stream(), content_type="application/x-ndjson")
