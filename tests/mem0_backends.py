from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar

from projects.models import Feature, Project, Task


class RecordingProjectMemoryStore:
    synced_features: ClassVar[list[dict[str, Any]]] = []
    synced_tasks: ClassVar[list[dict[str, Any]]] = []
    deleted_features: ClassVar[list[int]] = []
    deleted_tasks: ClassVar[list[int]] = []
    deleted_projects: ClassVar[list[int]] = []
    project_memories: ClassVar[dict[int, list[str]]] = defaultdict(list)

    @classmethod
    def reset(cls) -> None:
        cls.synced_features = []
        cls.synced_tasks = []
        cls.deleted_features = []
        cls.deleted_tasks = []
        cls.deleted_projects = []
        cls.project_memories = defaultdict(list)

    def sync_feature(self, *, feature: Feature) -> None:
        memory_text = f"feature:{feature.id}:{feature.name}:{feature.description}"
        self.synced_features.append(
            {
                "project_id": feature.project_id,
                "feature_id": feature.id,
                "memory": memory_text,
            }
        )
        self._replace_memory(
            project_id=feature.project_id,
            prefix=f"feature:{feature.id}:",
            memory_text=memory_text,
        )

    def sync_task(self, *, task: Task) -> None:
        memory_text = f"task:{task.id}:{task.title}:{task.status}"
        self.synced_tasks.append(
            {
                "project_id": task.feature.project_id,
                "task_id": task.id,
                "memory": memory_text,
            }
        )
        self._replace_memory(
            project_id=task.feature.project_id,
            prefix=f"task:{task.id}:",
            memory_text=memory_text,
        )

    def delete_feature(self, *, feature: Feature) -> None:
        self.deleted_features.append(feature.id)
        self._delete_memory(project_id=feature.project_id, prefix=f"feature:{feature.id}:")

    def delete_task(self, *, task: Task) -> None:
        self.deleted_tasks.append(task.id)
        self._delete_memory(project_id=task.feature.project_id, prefix=f"task:{task.id}:")

    def delete_project(self, *, project: Project) -> None:
        self.deleted_projects.append(project.id)
        self.project_memories.pop(project.id, None)

    def build_feature_chat_context(self, *, feature: Feature, user_message: str) -> str:
        del user_message
        project_memories = self.project_memories.get(feature.project_id, [])
        if not project_memories:
            return "No project feature/task memories are currently stored in mem0."
        lines = ["All saved project features/tasks from mem0:"]
        lines.extend(f"- {memory}" for memory in project_memories)
        return "\n".join(lines)

    def _replace_memory(self, *, project_id: int, prefix: str, memory_text: str) -> None:
        current = [memory for memory in self.project_memories[project_id] if not memory.startswith(prefix)]
        current.append(memory_text)
        self.project_memories[project_id] = current

    def _delete_memory(self, *, project_id: int, prefix: str) -> None:
        self.project_memories[project_id] = [
            memory for memory in self.project_memories[project_id] if not memory.startswith(prefix)
        ]
