from __future__ import annotations

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import NinjaAPI
from ninja.responses import Status
from ninja.errors import HttpError

from projects.models import Feature, Project
from projects.schemas import (
    FeatureCreateSchema,
    FeatureResponseSchema,
    FeatureUpdateSchema,
    ProjectCreateSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
)

api = NinjaAPI()


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
