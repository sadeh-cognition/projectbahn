from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

import httpx
from ninja import Schema
from pydantic import field_validator

from projects.models import Project, ProjectCodebaseAgentConfig


CODEBASE_AGENT_ENDPOINT_PATH = "/api/codebase-agent"


class CodebaseAgentConfigurationError(ValueError):
    pass


class CodebaseAgentRequestError(RuntimeError):
    pass


class CodebaseAgentRequestSchema(Schema):
    query: str

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Query cannot be blank.")
        return normalized_value


class CodebaseAgentResponseSchema(Schema):
    result: str


@dataclass(slots=True)
class CodebaseAgentClient:
    base_url: str
    timeout_seconds: float = 30.0

    def query(self, query: str) -> CodebaseAgentResponseSchema:
        payload = CodebaseAgentRequestSchema(query=query)
        response_payload = self._post_json(payload.model_dump(mode="json"))
        return CodebaseAgentResponseSchema.model_validate(response_payload)

    def stream_query(self, query: str) -> Iterator[str]:
        payload = CodebaseAgentRequestSchema(query=query)
        yield from self._post_json_stream(payload.model_dump(mode="json"))

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint_url = build_codebase_agent_endpoint_url(self.base_url)
        try:
            response = httpx.post(
                endpoint_url,
                json=payload,
                headers={"Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise CodebaseAgentRequestError(
                f"Codebase agent request to {endpoint_url} failed: {exc}"
            ) from exc

        if response.is_error:
            raise CodebaseAgentRequestError(
                f"Codebase agent request to {endpoint_url} failed with HTTP {response.status_code}: {response.text}"
            )

        try:
            decoded_payload = response.json()
        except json.JSONDecodeError as exc:
            raise CodebaseAgentRequestError(
                f"Codebase agent response from {endpoint_url} was not valid JSON."
            ) from exc

        if not isinstance(decoded_payload, dict):
            raise CodebaseAgentRequestError(
                f"Codebase agent response from {endpoint_url} was not a JSON object."
            )
        return decoded_payload

    def _post_json_stream(self, payload: dict[str, Any]) -> Iterator[str]:
        endpoint_url = build_codebase_agent_endpoint_url(self.base_url)
        try:
            with httpx.stream(
                "POST",
                endpoint_url,
                json=payload,
                headers={"Accept": "application/x-ndjson, application/json"},
                timeout=self.timeout_seconds,
            ) as response:
                if response.is_error:
                    response.read()
                    raise CodebaseAgentRequestError(
                        f"Codebase agent request to {endpoint_url} failed with HTTP "
                        f"{response.status_code}: {response.text}"
                    )

                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type and "application/x-ndjson" not in content_type:
                    response_body = response.read().decode("utf-8")
                    yield CodebaseAgentResponseSchema.model_validate_json(response_body).result
                    return

                for line in response.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    chunk = _parse_codebase_agent_stream_line(line)
                    if chunk:
                        yield chunk
        except httpx.RequestError as exc:
            raise CodebaseAgentRequestError(
                f"Codebase agent request to {endpoint_url} failed: {exc}"
            ) from exc


def build_codebase_agent_endpoint_url(base_url: str) -> str:
    cleaned_url = base_url.strip()
    if not cleaned_url:
        raise CodebaseAgentConfigurationError("Codebase agent URL is not configured.")

    parsed_url = urlparse(cleaned_url)
    if not parsed_url.scheme or not parsed_url.netloc:
        raise CodebaseAgentConfigurationError("Codebase agent URL must be an absolute URL.")

    if parsed_url.path.rstrip("/") == CODEBASE_AGENT_ENDPOINT_PATH:
        return cleaned_url

    return urljoin(cleaned_url.rstrip("/") + "/", CODEBASE_AGENT_ENDPOINT_PATH.lstrip("/"))


def get_codebase_agent_client_for_project(
    project: Project,
    *,
    timeout_seconds: float = 30.0,
) -> CodebaseAgentClient:
    config = ProjectCodebaseAgentConfig.get_for_project(project)
    if config is None or not config.url.strip():
        raise CodebaseAgentConfigurationError(
            "Configure the project codebase agent URL before using the codebase agent."
        )
    return CodebaseAgentClient(base_url=config.url, timeout_seconds=timeout_seconds)


def query_codebase_agent_for_project(
    *,
    project: Project,
    query: str,
    timeout_seconds: float = 30.0,
) -> CodebaseAgentResponseSchema:
    client = get_codebase_agent_client_for_project(project, timeout_seconds=timeout_seconds)
    return client.query(query)


def stream_codebase_agent_for_project(
    *,
    project: Project,
    query: str,
    timeout_seconds: float = 30.0,
) -> Iterator[str]:
    client = get_codebase_agent_client_for_project(project, timeout_seconds=timeout_seconds)
    yield from client.stream_query(query)


def _parse_codebase_agent_stream_line(line: str) -> str:
    if line.startswith("data:"):
        line = line.removeprefix("data:").strip()
    if line == "[DONE]":
        return ""

    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return line

    if not isinstance(payload, dict):
        return ""
    for key in ("text", "chunk", "result", "content"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""
