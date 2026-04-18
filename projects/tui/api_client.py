from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from urllib import error, parse, request

from ninja.errors import HttpError

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


class ApiTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any: ...


@dataclass(slots=True)
class UrllibApiTransport:
    base_url: str
    timeout_seconds: float = 5.0

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        query_string = ""
        if query:
            filtered_query = {key: value for key, value in query.items() if value not in (None, "")}
            if filtered_query:
                query_string = f"?{parse.urlencode(filtered_query)}"

        json_body = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        http_request = request.Request(
            url=f"{self.base_url.rstrip('/')}{path}{query_string}",
            data=json_body,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                if not response_body:
                    return None
                return json.loads(response_body)
        except error.HTTPError as exc:
            detail = self._extract_error_detail(exc)
            raise HttpError(exc.code, detail) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach API at {self.base_url}: {exc.reason}") from exc

    def _extract_error_detail(self, exc: error.HTTPError) -> str:
        response_body = exc.read().decode("utf-8")
        if not response_body:
            return f"Request failed with status {exc.code}."
        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError:
            return response_body
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        return response_body


@dataclass(slots=True)
class ApiClient:
    base_url: str
    timeout_seconds: float = 5.0
    transport: ApiTransport | None = None

    def __post_init__(self) -> None:
        if self.transport is None:
            self.transport = UrllibApiTransport(
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
            )

    def list_projects(self) -> list[ProjectResponseSchema]:
        payload = self._request("GET", "/projects")
        return [ProjectResponseSchema.model_validate(item) for item in payload]

    def create_project(self, project: ProjectCreateSchema) -> ProjectResponseSchema:
        return ProjectResponseSchema.model_validate(
            self._request("POST", "/projects", body=project.model_dump()),
        )

    def update_project(self, project_id: int, project: ProjectUpdateSchema) -> ProjectResponseSchema:
        return ProjectResponseSchema.model_validate(
            self._request("PUT", f"/projects/{project_id}", body=project.model_dump()),
        )

    def delete_project(self, project_id: int) -> None:
        self._request("DELETE", f"/projects/{project_id}")

    def list_features(self) -> list[FeatureResponseSchema]:
        payload = self._request("GET", "/features")
        return [FeatureResponseSchema.model_validate(item) for item in payload]

    def create_feature(self, feature: FeatureCreateSchema) -> FeatureResponseSchema:
        return FeatureResponseSchema.model_validate(
            self._request("POST", "/features", body=feature.model_dump()),
        )

    def update_feature(self, feature_id: int, feature: FeatureUpdateSchema) -> FeatureResponseSchema:
        return FeatureResponseSchema.model_validate(
            self._request("PUT", f"/features/{feature_id}", body=feature.model_dump()),
        )

    def delete_feature(self, feature_id: int) -> None:
        self._request("DELETE", f"/features/{feature_id}")

    def list_users(self) -> list[UserResponseSchema]:
        payload = self._request("GET", "/users")
        return [UserResponseSchema.model_validate(item) for item in payload]

    def list_tasks(
        self,
        *,
        project_id: int | None = None,
        feature_id: int | None = None,
        search: str | None = None,
        status: str | None = None,
        assignee: str | None = None,
        sort_by: str = "date_updated",
        sort_dir: str = "desc",
    ) -> list[TaskResponseSchema]:
        payload = self._request(
            "GET",
            "/tasks",
            query={
                "project_id": project_id,
                "feature_id": feature_id,
                "search": search,
                "status": status,
                "assignee": assignee,
                "sort_by": sort_by,
                "sort_dir": sort_dir,
            },
        )
        return [TaskResponseSchema.model_validate(item) for item in payload]

    def create_task(self, task: TaskCreateSchema) -> TaskResponseSchema:
        return TaskResponseSchema.model_validate(
            self._request("POST", "/tasks", body=task.model_dump()),
        )

    def update_task(self, task_id: int, task: TaskUpdateSchema) -> TaskResponseSchema:
        return TaskResponseSchema.model_validate(
            self._request("PUT", f"/tasks/{task_id}", body=task.model_dump()),
        )

    def delete_task(self, task_id: int) -> None:
        self._request("DELETE", f"/tasks/{task_id}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        if self.transport is None:
            raise RuntimeError("API transport was not configured.")
        return self.transport.request(method, path, body=body, query=query)
