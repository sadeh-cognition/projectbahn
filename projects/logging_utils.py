from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.json import JSON

_log_console = Console(color_system=None, force_terminal=False, width=120)


def format_payload_for_log(payload: Any) -> str:
    if isinstance(payload, dict | list):
        with _log_console.capture() as capture:
            _log_console.print(JSON.from_data(payload))
        return capture.get().rstrip()
    return str(payload)
