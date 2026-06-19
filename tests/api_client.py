from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from dj_rest_auth.utils import jwt_encode
from ninja.testing import TestClient


class AuthenticatedTestClient(TestClient):
    """Ninja client that sends a real bearer token on every API request."""

    def request(self, method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        user = kwargs.pop("user", None)
        if user is None:
            user_model = get_user_model()
            user = user_model.objects.order_by("pk").first()
            if user is None:
                user = user_model.objects.create(username="api-test-client")
        access_token, _refresh_token = jwt_encode(user)
        headers = kwargs.setdefault("headers", {})
        headers["Authorization"] = f"Bearer {access_token}"
        return super().request(method, path, *args, **kwargs)
