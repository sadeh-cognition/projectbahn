from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
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
def list_tasks(request: HttpRequest) -> list[Task]:
    return list(Task.objects.select_related("feature", "user").order_by("id"))


@api.post("/tasks", response=TaskResponseSchema)
def create_task(
    request: HttpRequest,
    payload: TaskCreateSchema,
) -> Task:
    feature = get_object_or_404(Feature, id=payload.feature_id)
    user = get_object_or_404(User, id=payload.user_id)
    return Task.objects.create(
        feature=feature,
        user=user,
        status=payload.status,
    )


@api.get("/tasks/{task_id}", response=TaskResponseSchema)
def get_task(request: HttpRequest, task_id: int) -> Task:
    return get_object_or_404(Task.objects.select_related("feature", "user"), id=task_id)


@api.put("/tasks/{task_id}", response=TaskResponseSchema)
def update_task(
    request: HttpRequest,
    task_id: int,
    payload: TaskUpdateSchema,
) -> Task:
    task = get_object_or_404(Task, id=task_id)
    feature = get_object_or_404(Feature, id=payload.feature_id)
    user = get_object_or_404(User, id=payload.user_id)
    task.feature = feature
    task.user = user
    task.status = payload.status
    task.save(update_fields=["feature", "user", "status", "date_updated"])
    return task


@api.delete("/tasks/{task_id}", response={204: None})
def delete_task(request: HttpRequest, task_id: int) -> Status[None]:
    task = get_object_or_404(Task, id=task_id)
    task.delete()
    return Status(204, None)
