from __future__ import annotations

from django.contrib.auth import get_user_model

from ninja.testing import TestClient

import pytest
from model_bakery import baker

from projects.api import api
from projects.schemas import UserResponseSchema

client = TestClient(api)
User = get_user_model()


@pytest.mark.django_db
def test_list_users_returns_username_ordered() -> None:
    baker.make(User, username="zoe")
    baker.make(User, username="alex")

    response = client.get("/users")

    assert response.status_code == 200
    body = [UserResponseSchema.model_validate(item) for item in response.json()]
    assert [item.username for item in body] == ["alex", "zoe"]
