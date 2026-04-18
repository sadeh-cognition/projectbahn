from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.db.models import Q, QuerySet
from ninja.errors import HttpError
from ninja import NinjaAPI
from ninja.responses import Status

from projects.models import Feature, Project, Task
from projects.schemas import (
    FeatureCreateSchema,
    FeatureResponseSchema,
    FeatureUpdateSchema,
    ProjectCreateSchema,
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


@api.get("/users", response=list[UserResponseSchema])
def list_users(request: HttpRequest) -> list[User]:
    return list(User.objects.order_by("username", "id"))


@api.get("/projects", response=list[ProjectResponseSchema])
def list_projects(request: HttpRequest) -> list[Project]:
    return list(Project.objects.order_by("id"))


@api.post("/projects", response=ProjectResponseSchema)
def create_project(
    request: HttpRequest,
    payload: ProjectCreateSchema,
) -> Project:
    return Project.objects.create(
        name=payload.name,
        description=payload.description,
    )


@api.get("/projects/{project_id}", response=ProjectResponseSchema)
def get_project(request: HttpRequest, project_id: int) -> Project:
    return get_object_or_404(Project, id=project_id)


@api.put("/projects/{project_id}", response=ProjectResponseSchema)
def update_project(
    request: HttpRequest,
    project_id: int,
    payload: ProjectUpdateSchema,
) -> Project:
    project = get_object_or_404(Project, id=project_id)
    project.name = payload.name
    project.description = payload.description
    project.save(update_fields=["name", "description", "date_updated"])
    return project


@api.delete("/projects/{project_id}", response={204: None})
def delete_project(request: HttpRequest, project_id: int) -> Status[None]:
    project = get_object_or_404(Project, id=project_id)
    project.delete()
    return Status(204, None)


@api.get("/features", response=list[FeatureResponseSchema])
def list_features(request: HttpRequest) -> list[Feature]:
    return list(Feature.objects.select_related("project", "parent_feature").order_by("id"))


@api.post("/features", response=FeatureResponseSchema)
def create_feature(
    request: HttpRequest,
    payload: FeatureCreateSchema,
) -> Feature:
    project = get_object_or_404(Project, id=payload.project_id)
    parent_feature = _get_parent_feature(payload.parent_feature_id)
    _validate_parent_feature(project=project, parent_feature=parent_feature)
    return Feature.objects.create(
        project=project,
        parent_feature=parent_feature,
        name=payload.name,
        description=payload.description,
    )


@api.get("/features/{feature_id}", response=FeatureResponseSchema)
def get_feature(request: HttpRequest, feature_id: int) -> Feature:
    return get_object_or_404(Feature.objects.select_related("project", "parent_feature"), id=feature_id)


@api.put("/features/{feature_id}", response=FeatureResponseSchema)
def update_feature(
    request: HttpRequest,
    feature_id: int,
    payload: FeatureUpdateSchema,
) -> Feature:
    feature = get_object_or_404(Feature, id=feature_id)
    project = get_object_or_404(Project, id=payload.project_id)
    parent_feature = _get_parent_feature(payload.parent_feature_id)
    _validate_parent_feature(project=project, parent_feature=parent_feature, feature_id=feature_id)
    feature.project = project
    feature.parent_feature = parent_feature
    feature.name = payload.name
    feature.description = payload.description
    feature.save(update_fields=["project", "parent_feature", "name", "description", "date_updated"])
    return feature


@api.delete("/features/{feature_id}", response={204: None})
def delete_feature(request: HttpRequest, feature_id: int) -> Status[None]:
    feature = get_object_or_404(Feature, id=feature_id)
    feature.delete()
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
    task = Task.objects.create(
        feature=feature,
        user=user,
        title=payload.title,
        description=payload.description,
        status=payload.status,
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
    task.feature = feature
    task.user = user
    task.title = payload.title
    task.description = payload.description
    task.status = payload.status
    task.save(update_fields=["feature", "user", "title", "description", "status", "date_updated"])
    return _serialize_task(_tasks_queryset().get(id=task.id))


@api.delete("/tasks/{task_id}", response={204: None})
def delete_task(request: HttpRequest, task_id: int) -> Status[None]:
    task = get_object_or_404(Task, id=task_id)
    task.delete()
    return Status(204, None)
