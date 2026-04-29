from __future__ import annotations

from ninja import NinjaAPI

api = NinjaAPI()

from projects.api import event_logs as event_logs  # noqa: E402,F401
from projects.api import feature_chat as feature_chat  # noqa: E402,F401
from projects.api import features as features  # noqa: E402,F401
from projects.api import projects as projects  # noqa: E402,F401
from projects.api import tasks as tasks  # noqa: E402,F401
from projects.api import users as users  # noqa: E402,F401
