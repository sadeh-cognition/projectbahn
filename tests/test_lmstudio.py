from __future__ import annotations

import importlib
import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from projbahn.mem0_settings import Mem0Settings
from projects.apps import ProjectsConfig
from projects.lmstudio import (
    LMStudioStartupError,
    build_lmstudio_management_base_url,
    ensure_lmstudio_embedding_model_loaded,
)


@dataclass(slots=True)
class RecordedRequest:
    method: str
    path: str
    body: dict[str, Any] | None


class LMStudioTestServer(ThreadingHTTPServer):
    models: list[dict[str, Any]]
    requests: list[RecordedRequest]


class LMStudioHandler(BaseHTTPRequestHandler):
    server: LMStudioTestServer

    def do_GET(self) -> None:  # noqa: N802
        self.server.requests.append(
            RecordedRequest(method="GET", path=self.path, body=None)
        )
        if self.path != "/api/v1/models":
            self.send_error(404)
            return
        self._send_json({"models": self.server.models})

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length).decode("utf-8")
        body = json.loads(payload) if payload else None
        self.server.requests.append(
            RecordedRequest(method="POST", path=self.path, body=body)
        )

        if self.path != "/api/v1/models/load":
            self.send_error(404)
            return

        if not isinstance(body, dict) or not isinstance(body.get("model"), str):
            self.send_error(400)
            return

        model_key = body["model"]
        for model in self.server.models:
            if model.get("key") != model_key:
                continue
            model["loaded_instances"] = [{"id": model_key, "config": {"context_length": 2048}}]
            self._send_json(
                {
                    "type": model.get("type"),
                    "instance_id": model_key,
                    "load_time_seconds": 0.01,
                    "status": "loaded",
                }
            )
            return

        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _send_json(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@pytest.fixture
def lmstudio_server() -> Any:
    server = LMStudioTestServer(("127.0.0.1", 0), LMStudioHandler)
    server.models = []
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_build_lmstudio_management_base_url_converts_openai_compatible_url() -> None:
    assert build_lmstudio_management_base_url("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/api/v1"
    assert build_lmstudio_management_base_url("http://127.0.0.1:1234/custom/v1/") == "http://127.0.0.1:1234/custom/api/v1"


def test_ensure_lmstudio_embedding_model_loaded_skips_when_model_is_already_loaded(
    monkeypatch,
    lmstudio_server: LMStudioTestServer,
) -> None:
    lmstudio_server.models = [
        {
            "key": "embed-custom",
            "type": "embedding",
            "loaded_instances": [{"id": "embed-custom", "config": {"context_length": 2048}}],
        }
    ]
    monkeypatch.setattr(
        "projbahn.settings.mem0_settings",
        Mem0Settings(
            embedder_model="embed-custom",
            lmstudio_base_url=f"http://127.0.0.1:{lmstudio_server.server_port}/v1",
            verify_lmstudio_on_startup=True,
            startup_timeout_seconds=1,
        ),
    )

    ensure_lmstudio_embedding_model_loaded()

    assert [(request.method, request.path) for request in lmstudio_server.requests] == [
        ("GET", "/api/v1/models")
    ]


def test_ensure_lmstudio_embedding_model_loaded_loads_unloaded_model(
    monkeypatch,
    lmstudio_server: LMStudioTestServer,
) -> None:
    lmstudio_server.models = [
        {
            "key": "embed-custom",
            "type": "embedding",
            "loaded_instances": [],
        }
    ]
    monkeypatch.setattr(
        "projbahn.settings.mem0_settings",
        Mem0Settings(
            embedder_model="embed-custom",
            lmstudio_base_url=f"http://127.0.0.1:{lmstudio_server.server_port}/v1",
            verify_lmstudio_on_startup=True,
            startup_timeout_seconds=1,
        ),
    )

    ensure_lmstudio_embedding_model_loaded()

    assert [(request.method, request.path) for request in lmstudio_server.requests] == [
        ("GET", "/api/v1/models"),
        ("POST", "/api/v1/models/load"),
    ]
    assert lmstudio_server.requests[1].body == {"model": "embed-custom"}
    assert lmstudio_server.models[0]["loaded_instances"]


def test_ensure_lmstudio_embedding_model_loaded_raises_when_model_is_missing(
    monkeypatch,
    lmstudio_server: LMStudioTestServer,
) -> None:
    lmstudio_server.models = [
        {
            "key": "other-model",
            "type": "embedding",
            "loaded_instances": [],
        }
    ]
    monkeypatch.setattr(
        "projbahn.settings.mem0_settings",
        Mem0Settings(
            embedder_model="embed-custom",
            lmstudio_base_url=f"http://127.0.0.1:{lmstudio_server.server_port}/v1",
            verify_lmstudio_on_startup=True,
            startup_timeout_seconds=1,
        ),
    )

    with pytest.raises(LMStudioStartupError, match="embed-custom"):
        ensure_lmstudio_embedding_model_loaded()


def test_projects_config_ready_runs_mlflow_and_lmstudio_startup_hooks(
    monkeypatch,
) -> None:
    calls: list[str] = []
    projects_module = importlib.import_module("projects")

    monkeypatch.setattr(
        "projects.observability.configure_dspy_mlflow",
        lambda: calls.append("mlflow"),
    )
    monkeypatch.setattr(
        "projects.lmstudio.ensure_lmstudio_embedding_model_loaded",
        lambda: calls.append("lmstudio"),
    )

    config = ProjectsConfig("projects", projects_module)

    config.ready()

    assert calls == ["mlflow", "lmstudio"]
