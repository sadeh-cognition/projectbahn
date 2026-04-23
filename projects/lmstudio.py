from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from projbahn import settings as app_settings

logger = logging.getLogger(__name__)


class LMStudioStartupError(RuntimeError):
    pass


def build_lmstudio_management_base_url(openai_base_url: str) -> str:
    parsed_url = urlsplit(openai_base_url.strip())
    if not parsed_url.scheme or not parsed_url.netloc:
        raise LMStudioStartupError(f"Invalid LM Studio base URL: {openai_base_url!r}")

    normalized_path = parsed_url.path.rstrip("/")
    if normalized_path.endswith("/api/v1"):
        management_path = normalized_path
    elif normalized_path.endswith("/v1"):
        management_path = f"{normalized_path[:-3]}/api/v1" or "/api/v1"
    elif normalized_path:
        management_path = f"{normalized_path}/api/v1"
    else:
        management_path = "/api/v1"

    return urlunsplit(
        SplitResult(
            scheme=parsed_url.scheme,
            netloc=parsed_url.netloc,
            path=management_path,
            query="",
            fragment="",
        )
    )


def ensure_lmstudio_embedding_model_loaded() -> None:
    if not app_settings.mem0_settings.verify_lmstudio_on_startup:
        return

    embedder_model = app_settings.mem0_settings.embedder_model.strip()
    if not embedder_model:
        raise LMStudioStartupError("PROJBAHN_MEM0_EMBEDDER_MODEL must not be blank.")

    management_base_url = build_lmstudio_management_base_url(
        app_settings.mem0_settings.lmstudio_base_url
    )
    models_response = _request_json(
        method="GET",
        url=f"{management_base_url}/models",
    )
    if not models_response.get("models"):
        raise LMStudioStartupError(
            "No models returned from LMSTudio API",
        )

    model_definition = _find_model_definition(
        models=models_response["models"], model_key=embedder_model
    )
    if model_definition is None:
        raise LMStudioStartupError(
            f"Model '{embedder_model} not returned by LMStudio API!"
        )
    if model_definition.get("type") != "embedding":
        raise LMStudioStartupError(
            f"Configured embedding model '{embedder_model}' is registered in LM Studio as "
            f"{model_definition.get('type')!r}, not 'embedding'."
        )
    if model_definition.get("loaded_instances"):
        logger.info("LM Studio embedding model '%s' is already loaded.", embedder_model)
        return

    load_response = _request_json(
        method="POST",
        url=f"{management_base_url}/models/load",
        body={"model": embedder_model},
    )
    if load_response.get("status") != "loaded":
        raise LMStudioStartupError(
            f"LM Studio did not report a loaded status for embedding model '{embedder_model}'."
        )
    if load_response.get("type") != "embedding":
        raise LMStudioStartupError(
            f"LM Studio loaded '{embedder_model}' as {load_response.get('type')!r}, not "
            f"'embedding'."
        )
    logger.info("Loaded LM Studio embedding model '%s' during startup.", embedder_model)


def _find_model_definition(*, models: object, model_key: str) -> dict[str, Any] | None:
    if not isinstance(models, list):
        raise LMStudioStartupError("LM Studio returned an invalid models payload.")

    for model in models:
        if isinstance(model, dict) and model.get("key") == model_key:
            return model
    return None


def _request_json(
    *, method: str, url: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        url=url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urlopen(
            request,
            timeout=app_settings.mem0_settings.startup_timeout_seconds,
        ) as response:
            decoded = response.read().decode("utf-8")
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise LMStudioStartupError(
            f"LM Studio request to {url} failed with HTTP {exc.code}: {response_body}"
        ) from exc
    except URLError as exc:
        reason = exc.reason if exc.reason is not None else str(exc)
        raise LMStudioStartupError(
            f"Could not reach LM Studio at {url}: {reason}"
        ) from exc

    try:
        result = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise LMStudioStartupError(
            f"LM Studio returned invalid JSON from {url}: {decoded}"
        ) from exc

    if not isinstance(result, dict):
        raise LMStudioStartupError(
            f"LM Studio returned an unexpected response body from {url}."
        )
    return result
