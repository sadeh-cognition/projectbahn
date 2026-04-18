from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from projects.frontend.services import (
    build_feature_options,
    build_feature_tree,
    features_for_project,
    flatten_feature_tree,
)
from projects.models import Feature, Project, Task

User = get_user_model()

TASK_SORT_OPTIONS = [
    ("date_updated", "Recently updated"),
    ("date_created", "Recently created"),
    ("title", "Title"),
    ("status", "Status"),
    ("feature", "Feature"),
    ("assignee", "Assignee"),
]
TASK_SORT_DIRECTIONS = [("desc", "Descending"), ("asc", "Ascending")]
WORKSPACE_TABS = {"tasks", "features", "project_settings"}


@dataclass(slots=True)
class TaskFilters:
    search: str = ""
    status: str = ""
    assignee: str = ""
    sort_by: str = "date_updated"
    sort_dir: str = "desc"


def dashboard(request: HttpRequest) -> HttpResponse:
    workspace_context = _build_workspace_context(
        request=request,
        project_id=_parse_int(request.GET.get("project_id")),
    )
    return render(request, "projects/dashboard.html", workspace_context)


def workspace(request: HttpRequest) -> HttpResponse:
    context = _build_workspace_context(
        request=request,
        project_id=_parse_int(request.GET.get("project_id")),
    )
    return render(request, "projects/partials/workspace.html", context)


def _build_workspace_context(
    *,
    request: HttpRequest,
    project_id: int | None,
) -> dict[str, object]:
    projects = list(Project.objects.order_by("id"))
    selected_project = next((project for project in projects if project.id == project_id), None)

    if selected_project is None:
        return {
            "projects": projects,
            "selected_project": None,
            "active_tab": "tasks",
        }

    project_features = features_for_project(
        project_id=selected_project.id,
        features=list(
            Feature.objects.select_related("project", "parent_feature").filter(project_id=selected_project.id),
        ),
    )
    feature_tree = build_feature_tree(project_features)
    feature_options = build_feature_options(feature_tree)
    feature_name_by_id = {feature.id: feature.name for feature in project_features}
    feature_rows = [
        {
            "depth": depth,
            "feature": feature,
            "parent_name": (
                feature_name_by_id.get(feature.parent_feature_id, "Unknown")
                if feature.parent_feature_id is not None
                else "Root"
            ),
        }
        for depth, feature in flatten_feature_tree(feature_tree)
    ]
    filters = _task_filters_from_request(request)
    tasks = _task_rows(project_id=selected_project.id, filters=filters)
    users = list(User.objects.order_by("username", "id"))

    return {
        "projects": projects,
        "selected_project": selected_project,
        "active_tab": _active_tab_from_request(request),
        "feature_tree": feature_tree,
        "feature_options": feature_options,
        "feature_rows": feature_rows,
        "users": users,
        "tasks": tasks,
        "task_filters": filters,
        "task_sort_options": TASK_SORT_OPTIONS,
        "task_sort_directions": TASK_SORT_DIRECTIONS,
        "edit_feature": _select_feature_for_edit(
            project_features=project_features,
            edit_feature_id=_parse_int(request.GET.get("edit_feature_id")),
        ),
        "edit_task": _select_task_for_edit(
            tasks=tasks,
            edit_task_id=_parse_int(request.GET.get("edit_task_id")),
        ),
        "dashboard_url": _dashboard_url(project_id=selected_project.id, tab=_active_tab_from_request(request)),
        "workspace_url": reverse("workspace"),
    }


def _task_rows(*, project_id: int, filters: TaskFilters) -> list[dict[str, object]]:
    queryset = Task.objects.select_related("feature__project", "user").filter(feature__project_id=project_id)

    if filters.search:
        queryset = queryset.filter(
            Q(title__icontains=filters.search)
            | Q(description__icontains=filters.search)
            | Q(feature__name__icontains=filters.search)
            | Q(user__username__icontains=filters.search),
        )
    if filters.status:
        queryset = queryset.filter(status__icontains=filters.status)
    if filters.assignee:
        queryset = queryset.filter(user__username__icontains=filters.assignee)

    sort_fields = {
        "title": "title",
        "status": "status",
        "feature": "feature__name",
        "assignee": "user__username",
        "date_created": "date_created",
        "date_updated": "date_updated",
    }
    order_field = sort_fields.get(filters.sort_by, "date_updated")
    ordering_prefix = "" if filters.sort_dir == "asc" else "-"
    tasks = queryset.order_by(f"{ordering_prefix}{order_field}", f"{ordering_prefix}id")

    return [
        {
            "id": task.id,
            "project_id": task.feature.project_id,
            "project_name": task.feature.project.name,
            "feature_id": task.feature_id,
            "feature_name": task.feature.name,
            "user_id": task.user_id,
            "user_username": task.user.get_username(),
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "date_created": task.date_created,
            "date_updated": task.date_updated,
        }
        for task in tasks
    ]


def _task_filters_from_request(request: HttpRequest) -> TaskFilters:
    return TaskFilters(
        search=request.GET.get("search", "").strip(),
        status=request.GET.get("status", "").strip(),
        assignee=request.GET.get("assignee", "").strip(),
        sort_by=request.GET.get("sort_by", "date_updated").strip() or "date_updated",
        sort_dir=request.GET.get("sort_dir", "desc").strip() or "desc",
    )


def _select_feature_for_edit(
    *,
    project_features: list[Feature],
    edit_feature_id: int | None,
) -> Feature | None:
    if edit_feature_id is None:
        return None
    return next((feature for feature in project_features if feature.id == edit_feature_id), None)


def _select_task_for_edit(
    *,
    tasks: list[dict[str, object]],
    edit_task_id: int | None,
) -> dict[str, object] | None:
    if edit_task_id is None:
        return None
    return next((task for task in tasks if task["id"] == edit_task_id), None)


def _parse_int(raw_value: str | None) -> int | None:
    if raw_value in (None, ""):
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


def _active_tab_from_request(request: HttpRequest) -> str:
    if _parse_int(request.GET.get("edit_feature_id")) is not None:
        return "features"
    if _parse_int(request.GET.get("edit_task_id")) is not None:
        return "tasks"
    tab = request.GET.get("tab", "tasks").strip().lower()
    if tab in WORKSPACE_TABS:
        return tab
    return "tasks"


def _dashboard_url(
    *,
    project_id: int | None = None,
    edit_feature_id: int | None = None,
    edit_task_id: int | None = None,
    tab: str | None = None,
) -> str:
    params = {
        "project_id": project_id,
        "edit_feature_id": edit_feature_id,
        "edit_task_id": edit_task_id,
        "tab": tab if tab in WORKSPACE_TABS else None,
    }
    filtered_params = {key: value for key, value in params.items() if value is not None}
    base_url = reverse("dashboard")
    if not filtered_params:
        return base_url
    return f"{base_url}?{urlencode(filtered_params)}"
