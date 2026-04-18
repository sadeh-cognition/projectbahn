from __future__ import annotations

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import NinjaAPI
from ninja.responses import Status

from projects.models import Project
from projects.schemas import (
    ProjectCreateSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
)

api = NinjaAPI()


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
