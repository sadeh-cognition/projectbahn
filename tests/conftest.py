from __future__ import annotations

import pytest

from projects import project_memory
from tests.mem0_backends import RecordingProjectMemoryStore


@pytest.fixture(autouse=True)
def disable_mem0_for_tests(monkeypatch) -> None:
    RecordingProjectMemoryStore.reset()
    monkeypatch.setattr(project_memory, "Mem0ProjectMemoryStore", RecordingProjectMemoryStore)
