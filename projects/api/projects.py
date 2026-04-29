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
    require_authenticated_user,
    serialize_project,
    serialize_project_codebase_agent_config,
    serialize_project_llm_config,
)
from projects.models import (
    EventLog,
    Feature,
    Project,
    ProjectCodebaseAgentConfig,
    ProjectLLMConfig,
    Task,
)
from projects.project_memory import (
    ProjectMemoryError,
    delete_project_memories,
)
from projects.schemas import (
    ProjectCodebaseAgentConfigResponseSchema,
    ProjectCodebaseAgentConfigUpdateSchema,
    ProjectCreateSchema,
    ProjectLLMConfigResponseSchema,
    ProjectLLMConfigUpdateSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
)


@api.get("/projects", response=list[ProjectResponseSchema])
def list_projects(request: HttpRequest) -> list[ProjectResponseSchema]:
    return [serialize_project(project) for project in Project.get_all_ordered()]


@api.post("/projects", response=ProjectResponseSchema)
def create_project(
    request: HttpRequest,
    payload: ProjectCreateSchema,
) -> ProjectResponseSchema:
    with transaction.atomic():
        project = Project.create_project(
            name=payload.name,
            description=payload.description,
        )
        create_event_log(
            entity_type=EventLog.EntityType.PROJECT,
            entity_id=project.id,
            event_type=EventLog.EventType.CREATED,
        )
    return serialize_project(project)


@api.get("/projects/{project_id}", response=ProjectResponseSchema)
def get_project(request: HttpRequest, project_id: int) -> ProjectResponseSchema:
    return serialize_project(Project.get_by_id_or_404(project_id))


@api.get("/projects/{project_id}/llm-config", response=ProjectLLMConfigResponseSchema)
def get_project_llm_config(
    request: HttpRequest, project_id: int
) -> ProjectLLMConfigResponseSchema:
    project = Project.get_by_id_or_404(project_id)
    return serialize_project_llm_config(project)


@api.get(
    "/projects/{project_id}/codebase-agent-config",
    response=ProjectCodebaseAgentConfigResponseSchema,
)
def get_project_codebase_agent_config(
    request: HttpRequest,
    project_id: int,
) -> ProjectCodebaseAgentConfigResponseSchema:
    project = Project.get_by_id_or_404(project_id)
    return serialize_project_codebase_agent_config(project)


@api.put("/projects/{project_id}", response=ProjectResponseSchema)
def update_project(
    request: HttpRequest,
    project_id: int,
    payload: ProjectUpdateSchema,
) -> ProjectResponseSchema:
    project = Project.get_by_id_or_404(project_id)
    updated_values = {
        "name": payload.name,
        "description": payload.description,
    }
    event_details = build_change_details(project, updated_values)
    with transaction.atomic():
        project.name = payload.name
        project.description = payload.description
        project.save(update_fields=["name", "description", "date_updated"])
        create_event_log(
            entity_type=EventLog.EntityType.PROJECT,
            entity_id=project.id,
            event_type=EventLog.EventType.MODIFIED,
            event_details=event_details,
        )
    return serialize_project(project)


@api.put("/projects/{project_id}/llm-config", response=ProjectLLMConfigResponseSchema)
def update_project_llm_config(
    request: HttpRequest,
    project_id: int,
    payload: ProjectLLMConfigUpdateSchema,
) -> ProjectLLMConfigResponseSchema:
    require_authenticated_user(request)
    project = Project.get_by_id_or_404(project_id)
    with transaction.atomic():
        config, _ = ProjectLLMConfig.get_or_create_for_project(project=project)
        config.provider = payload.provider
        config.llm_name = payload.llm_name
        if payload.api_key:
            config.set_api_key(payload.api_key)
            config.save(
                update_fields=[
                    "provider",
                    "llm_name",
                    "api_key_hash",
                    "encrypted_api_key",
                    "date_updated",
                ]
            )
        else:
            config.save(update_fields=["provider", "llm_name", "date_updated"])
    return serialize_project_llm_config(project)


@api.put(
    "/projects/{project_id}/codebase-agent-config",
    response=ProjectCodebaseAgentConfigResponseSchema,
)
def update_project_codebase_agent_config(
    request: HttpRequest,
    project_id: int,
    payload: ProjectCodebaseAgentConfigUpdateSchema,
) -> ProjectCodebaseAgentConfigResponseSchema:
    require_authenticated_user(request)
    project = Project.get_by_id_or_404(project_id)
    with transaction.atomic():
        config, _ = ProjectCodebaseAgentConfig.get_or_create_for_project(
            project=project
        )
        config.url = payload.url.strip()
        config.save(update_fields=["url", "date_updated"])
    return serialize_project_codebase_agent_config(project)


@api.delete("/projects/{project_id}", response={204: None})
def delete_project(request: HttpRequest, project_id: int) -> Status[None]:
    project = Project.get_by_id_or_404(project_id)
    deleted_project_id = project.id
    feature_ids = list(Feature.get_ids_for_project(deleted_project_id))
    task_ids = list(Task.get_ids_for_project(deleted_project_id))
    with transaction.atomic():
        try:
            delete_project_memories(project=project)
        except ProjectMemoryError as exc:
            raise HttpError(503, str(exc)) from exc
        project.delete()
        EventLog.bulk_create_logs(
            [
                *[
                    build_deleted_event_log(EventLog.EntityType.TASK, task_id)
                    for task_id in task_ids
                ],
                *[
                    build_deleted_event_log(EventLog.EntityType.FEATURE, feature_id)
                    for feature_id in feature_ids
                ],
                build_deleted_event_log(
                    EventLog.EntityType.PROJECT, deleted_project_id
                ),
            ]
        )
    return Status(204, None)
