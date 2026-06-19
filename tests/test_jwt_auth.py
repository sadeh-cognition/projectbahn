from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client
from dj_rest_auth.utils import jwt_encode
from ninja.testing import TestClient
from rest_framework_simplejwt.tokens import RefreshToken

import pytest

from projects.api import api

User = get_user_model()


def create_user(*, username: str, password: str):
    user = User.objects.create(username=username)
    user.set_password(password)
    user.save(update_fields=["password"])
    return user


@pytest.mark.django_db
def test_dj_rest_auth_login_returns_jwt_and_httponly_cookies() -> None:
    create_user(username="alex", password="correct-password")

    response = Client().post(
        "/api/auth/login/",
        data={"username": "alex", "password": "correct-password"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["access"]
    assert response.json()["refresh"] == ""
    assert response.cookies["projbahn-access"]["httponly"] is True
    assert response.cookies["projbahn-refresh"]["httponly"] is True


@pytest.mark.django_db
def test_dj_rest_auth_login_rejects_invalid_credentials() -> None:
    create_user(username="alex", password="correct-password")

    response = Client().post(
        "/api/auth/login/",
        data={"username": "alex", "password": "wrong-password"},
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_api_rejects_missing_invalid_and_refresh_tokens() -> None:
    user = create_user(username="alex", password="correct-password")
    refresh = RefreshToken.for_user(user)
    client = TestClient(api)

    missing_response = client.get("/projects")
    invalid_response = client.get(
        "/projects", headers={"Authorization": "Bearer invalid-token"}
    )
    refresh_response = client.get(
        "/projects", headers={"Authorization": f"Bearer {refresh}"}
    )

    assert missing_response.status_code == 401
    assert invalid_response.status_code == 401
    assert refresh_response.status_code == 401


@pytest.mark.django_db
def test_api_accepts_access_token_in_bearer_header() -> None:
    user = create_user(username="alex", password="correct-password")
    access_token, _refresh_token = jwt_encode(user)

    response = TestClient(api).get(
        "/projects",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_api_accepts_dj_rest_auth_access_cookie() -> None:
    create_user(username="alex", password="correct-password")
    client = Client(enforce_csrf_checks=True)
    login_response = client.post(
        "/api/auth/login/",
        data={"username": "alex", "password": "correct-password"},
        content_type="application/json",
    )
    csrf_response = client.get("/projects/")
    csrf_token = csrf_response.cookies["csrftoken"].value

    response = client.get(
        "/api/projects",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert login_response.status_code == 200
    assert response.status_code == 200


@pytest.mark.django_db
def test_dj_rest_auth_refresh_issues_new_access_token() -> None:
    create_user(username="alex", password="correct-password")
    client = Client()
    client.post(
        "/api/auth/login/",
        data={"username": "alex", "password": "correct-password"},
        content_type="application/json",
    )

    response = client.post("/api/auth/token/refresh/", data={})

    assert response.status_code == 200
    assert response.json()["access"]
    assert response.cookies["projbahn-access"]["httponly"] is True


@pytest.mark.django_db
def test_web_logout_clears_jwt_cookies() -> None:
    user = create_user(username="alex", password="correct-password")
    client = Client()
    client.force_login(user)
    client.get("/")

    response = client.post("/logout/")

    assert response.status_code == 302
    assert response.cookies["projbahn-access"]["max-age"] == 0
    assert response.cookies["projbahn-refresh"]["max-age"] == 0
