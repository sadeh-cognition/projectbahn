from __future__ import annotations

import os

os.environ.setdefault("LLM_API_KEY_ENCRYPTION_KEY", "test-llm-api-key-encryption-key")
os.environ.setdefault("PROJBAHN_DSPY_MLFLOW_ENABLED", "false")
os.environ.setdefault("PROJBAHN_MEM0_EMBEDDER_MODEL", "embed-default")
os.environ.setdefault("PROJBAHN_MEM0_VERIFY_LMSTUDIO_ON_STARTUP", "false")

from projbahn.settings import *  # noqa: F403
