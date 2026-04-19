from __future__ import annotations

from collections.abc import Callable
import json
import logging

from django.http import HttpRequest, HttpResponse

from projects.rich_logging import format_payload_for_log

logger = logging.getLogger("projects.http_server")


class ApiResponseLoggingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        self._log_response(request, response)
        return response

    def _log_response(self, request: HttpRequest, response: HttpResponse) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        if not request.path.startswith("/api/"):
            return
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("application/json"):
            return
        if not response.content:
            return
        try:
            payload = json.loads(response.content.decode(response.charset or "utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        logger.debug(
            "HTTP %s %s returned %s\n%s",
            request.method,
            request.get_full_path(),
            response.status_code,
            format_payload_for_log(payload),
        )
