from __future__ import annotations

from django.http import HttpRequest

from projects.api import api
from projects.api.common import User
from projects.schemas import UserResponseSchema


@api.get("/users", response=list[UserResponseSchema])
def list_users(request: HttpRequest) -> list[User]:
    return list(User.objects.order_by("username", "id"))
