from __future__ import annotations

from typing import cast

from django.http import HttpRequest
from dj_rest_auth.jwt_auth import JWTCookieAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from ninja.security.base import AuthBase


class DjangoUserJWTAuth(AuthBase):
    openapi_type = "http"
    openapi_scheme = "bearer"

    def __call__(self, request: HttpRequest) -> object | None:
        authorization = request.headers.get("Authorization")
        if authorization and "HTTP_AUTHORIZATION" not in request.META:
            request.META["HTTP_AUTHORIZATION"] = authorization
        try:
            result = JWTCookieAuthentication().authenticate(cast(Request, request))
        except AuthenticationFailed:
            return None
        if result is None:
            return None
        user, validated_token = result
        request.user = user
        setattr(request, "auth", validated_token)
        return user


django_user_jwt_auth = DjangoUserJWTAuth()
