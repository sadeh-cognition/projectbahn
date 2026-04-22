from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def disable_mem0_for_tests(settings) -> None:
    settings.PROJBAHN_MEM0_ENABLED = False
