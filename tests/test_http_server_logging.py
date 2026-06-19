from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.test import Client
from dj_rest_auth.utils import jwt_encode

import pytest
from model_bakery import baker

from projects.models import Project
from projects.schemas import ProjectResponseSchema


@pytest.fixture
def client() -> Client:
    user = get_user_model().objects.create_user(username="http-logging-user")
    access_token, _refresh_token = jwt_encode(user)
    return Client(HTTP_AUTHORIZATION=f"Bearer {access_token}")


@pytest.fixture
def project() -> Project:
    return baker.make(Project, name="Server Logging", description="Pretty JSON logging")


@pytest.mark.django_db
def test_server_logs_pretty_json_for_successful_api_response(
    client: Client,
    project: Project,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="projects.http_server"):
        response = client.get("/api/projects")

    assert response.status_code == 200
    body = [ProjectResponseSchema.model_validate(item) for item in response.json()]
    assert [item.id for item in body] == [project.id]
    assert [item.entity_type for item in body] == ["Project"]
    assert "HTTP GET /api/projects returned 200" in caplog.text
    assert '"name": "Server Logging"' in caplog.text


@pytest.mark.django_db
def test_server_logs_pretty_json_for_error_api_response(
    client: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="projects.http_server"):
        response = client.get("/api/event-logs?page=0")

    assert response.status_code == 400
    assert response.json()["detail"] == "Page must be greater than or equal to 1."
    assert "HTTP GET /api/event-logs?page=0 returned 400" in caplog.text
    assert '"detail": "Page must be greater than or equal to 1."' in caplog.text
