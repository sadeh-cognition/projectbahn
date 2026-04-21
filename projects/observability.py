from __future__ import annotations

from typing import Any

from django.conf import settings

_mlflow_autolog_initialized = False


def mlflow_tracing_enabled() -> bool:
    tracking_uri = settings.PROJBAHN_DSPY_MLFLOW_TRACKING_URI.strip()
    return bool(settings.PROJBAHN_DSPY_MLFLOW_ENABLED and tracking_uri)


def configure_dspy_mlflow(*, mlflow_module: Any | None = None) -> bool:
    global _mlflow_autolog_initialized

    if not mlflow_tracing_enabled():
        return False
    if _mlflow_autolog_initialized:
        return True

    if mlflow_module is None:
        import mlflow as mlflow_module

    mlflow_module.set_tracking_uri(settings.PROJBAHN_DSPY_MLFLOW_TRACKING_URI.strip())
    mlflow_module.set_experiment(settings.PROJBAHN_DSPY_MLFLOW_EXPERIMENT_NAME.strip())
    mlflow_module.dspy.autolog()
    _mlflow_autolog_initialized = True
    return True


def reset_dspy_mlflow_state() -> None:
    global _mlflow_autolog_initialized
    _mlflow_autolog_initialized = False
