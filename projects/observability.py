from __future__ import annotations

import logging
from typing import Any

from projbahn import settings as app_settings

_mlflow_autolog_initialized = False
logger = logging.getLogger(__name__)


def mlflow_tracing_enabled() -> bool:
    tracking_uri = app_settings.dspy_settings.mlflow_tracking_uri.strip()
    return bool(app_settings.dspy_settings.mlflow_enabled and tracking_uri)


def configure_dspy_mlflow(*, mlflow_module: Any | None = None) -> bool:
    global _mlflow_autolog_initialized

    if not mlflow_tracing_enabled():
        tracking_uri = app_settings.dspy_settings.mlflow_tracking_uri.strip()
        if tracking_uri and not app_settings.dspy_settings.mlflow_enabled:
            logger.info(
                "DSPy MLflow tracing is disabled. Set PROJBAHN_DSPY_MLFLOW_ENABLED=true to enable tracing to %s.",
                tracking_uri,
            )
        return False
    if _mlflow_autolog_initialized:
        return True

    if mlflow_module is None:
        import mlflow as mlflow_module

    mlflow_module.set_tracking_uri(app_settings.dspy_settings.mlflow_tracking_uri.strip())
    mlflow_module.set_experiment(app_settings.dspy_settings.mlflow_experiment_name.strip())
    mlflow_module.dspy.autolog()
    _mlflow_autolog_initialized = True
    return True


def reset_dspy_mlflow_state() -> None:
    global _mlflow_autolog_initialized
    _mlflow_autolog_initialized = False
