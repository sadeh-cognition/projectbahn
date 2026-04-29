from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from model_bakery import baker

from projects.codebase_agent_client import (
    CodebaseAgentClient,
    CodebaseAgentConfigurationError,
    CodebaseAgentRequestError,
    CodebaseAgentRequestSchema,
    CodebaseAgentResponseSchema,
    build_codebase_agent_endpoint_url,
    get_codebase_agent_client_for_project,
    query_codebase_agent_for_project,
)
from projects.models import Project, ProjectCodebaseAgentConfig


@dataclass(slots=True)
class RecordedRequest:
    method: str
    path: str
    body: dict[str, Any] | None


class CodebaseAgentTestServer(ThreadingHTTPServer):
    requests: list[RecordedRequest]
    response_status: int
    response_body: dict[str, Any] | list[Any] | str
    response_content_type: str


class CodebaseAgentHandler(BaseHTTPRequestHandler):
    server: CodebaseAgentTestServer

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length).decode("utf-8")
        body = json.loads(payload) if payload else None
        self.server.requests.append(
            RecordedRequest(method="POST", path=self.path, body=body)
        )

        if self.path != "/api/codebase-agent":
            self.send_error(404)
            return

        if self.server.response_content_type == "application/x-ndjson" and isinstance(
            self.server.response_body, list
        ):
            encoded_body = "\n".join(
                item if isinstance(item, str) else json.dumps(item)
                for item in self.server.response_body
            ).encode("utf-8")
        elif isinstance(self.server.response_body, str):
            encoded_body = self.server.response_body.encode("utf-8")
        else:
            encoded_body = json.dumps(self.server.response_body).encode("utf-8")

        self.send_response(self.server.response_status)
        self.send_header("Content-Type", self.server.response_content_type)
        self.send_header("Content-Length", str(len(encoded_body)))
        self.end_headers()
        self.wfile.write(encoded_body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@pytest.fixture
def codebase_agent_server() -> Any:
    server = CodebaseAgentTestServer(("127.0.0.1", 0), CodebaseAgentHandler)
    server.requests = []
    server.response_status = 200
    server.response_body = {"result": "Found health in agentbahn/api.py"}
    server.response_content_type = "application/json"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_build_codebase_agent_endpoint_url_uses_server_base_url() -> None:
    assert (
        build_codebase_agent_endpoint_url("http://localhost:8002")
        == "http://localhost:8002/api/codebase-agent"
    )


def test_build_codebase_agent_endpoint_url_keeps_full_endpoint_url() -> None:
    assert (
        build_codebase_agent_endpoint_url("http://localhost:8002/api/codebase-agent")
        == "http://localhost:8002/api/codebase-agent"
    )


def test_build_codebase_agent_endpoint_url_rejects_blank_url() -> None:
    with pytest.raises(CodebaseAgentConfigurationError, match="not configured"):
        build_codebase_agent_endpoint_url("  ")


def test_build_codebase_agent_endpoint_url_rejects_relative_url() -> None:
    with pytest.raises(CodebaseAgentConfigurationError, match="absolute URL"):
        build_codebase_agent_endpoint_url("/api/codebase-agent")


def test_codebase_agent_request_schema_trims_query() -> None:
    payload = CodebaseAgentRequestSchema(query="  health  ")

    assert payload.query == "health"


def test_codebase_agent_request_schema_rejects_blank_query() -> None:
    with pytest.raises(ValueError, match="Query cannot be blank"):
        CodebaseAgentRequestSchema(query="  ")


def test_codebase_agent_client_posts_query_and_parses_response(
    codebase_agent_server: CodebaseAgentTestServer,
) -> None:
    client = CodebaseAgentClient(
        base_url=f"http://127.0.0.1:{codebase_agent_server.server_port}"
    )

    response = client.query("health")

    assert response == CodebaseAgentResponseSchema(result="Found health in agentbahn/api.py")
    assert codebase_agent_server.requests == [
        RecordedRequest(method="POST", path="/api/codebase-agent", body={"query": "health"})
    ]


def test_codebase_agent_client_streams_ndjson_chunks(
    codebase_agent_server: CodebaseAgentTestServer,
) -> None:
    codebase_agent_server.response_content_type = "application/x-ndjson"
    codebase_agent_server.response_body = [
        {"type": "chunk", "text": "Found "},
        {"type": "chunk", "text": "health"},
        {"type": "done"},
    ]
    client = CodebaseAgentClient(
        base_url=f"http://127.0.0.1:{codebase_agent_server.server_port}"
    )

    chunks = list(client.stream_query("health"))

    assert chunks == ["Found ", "health"]
    assert codebase_agent_server.requests == [
        RecordedRequest(method="POST", path="/api/codebase-agent", body={"query": "health"})
    ]


def test_codebase_agent_client_raises_request_error_for_http_error(
    codebase_agent_server: CodebaseAgentTestServer,
) -> None:
    codebase_agent_server.response_status = 422
    codebase_agent_server.response_body = {"detail": "Query cannot be blank."}
    client = CodebaseAgentClient(
        base_url=f"http://127.0.0.1:{codebase_agent_server.server_port}"
    )

    with pytest.raises(CodebaseAgentRequestError, match="HTTP 422"):
        client.query("health")


def test_codebase_agent_client_raises_request_error_for_invalid_json(
    codebase_agent_server: CodebaseAgentTestServer,
) -> None:
    codebase_agent_server.response_body = "not-json"
    client = CodebaseAgentClient(
        base_url=f"http://127.0.0.1:{codebase_agent_server.server_port}"
    )

    with pytest.raises(CodebaseAgentRequestError, match="not valid JSON"):
        client.query("health")


@pytest.mark.django_db
def test_get_codebase_agent_client_for_project_uses_project_config() -> None:
    project = baker.make(Project)
    ProjectCodebaseAgentConfig.objects.create(
        project=project,
        url="http://localhost:8002",
    )

    client = get_codebase_agent_client_for_project(project)

    assert client.base_url == "http://localhost:8002"


@pytest.mark.django_db
def test_get_codebase_agent_client_for_project_requires_config() -> None:
    project = baker.make(Project)

    with pytest.raises(CodebaseAgentConfigurationError, match="Configure"):
        get_codebase_agent_client_for_project(project)


@pytest.mark.django_db
def test_query_codebase_agent_for_project_uses_project_config(
    codebase_agent_server: CodebaseAgentTestServer,
) -> None:
    project = baker.make(Project)
    ProjectCodebaseAgentConfig.objects.create(
        project=project,
        url=f"http://127.0.0.1:{codebase_agent_server.server_port}",
    )

    response = query_codebase_agent_for_project(project=project, query="health")

    assert response.result == "Found health in agentbahn/api.py"
    assert codebase_agent_server.requests == [
        RecordedRequest(method="POST", path="/api/codebase-agent", body={"query": "health"})
    ]
