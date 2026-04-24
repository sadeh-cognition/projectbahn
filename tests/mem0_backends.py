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
    project_memory_entries: ClassVar[dict[int, list[dict[str, Any]]]] = defaultdict(list)

    @classmethod
    def reset(cls) -> None:
        cls.synced_features = []
        cls.synced_tasks = []
        cls.deleted_features = []
        cls.deleted_tasks = []
        cls.deleted_projects = []
        cls.project_memories = defaultdict(list)
        cls.project_memory_entries = defaultdict(list)

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
            metadata={
                "entity_type": "feature",
                "entity_id": feature.id,
            },
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
            metadata={
                "entity_type": "task",
                "entity_id": task.id,
                "feature_id": task.feature_id,
            },
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

    def search_feature_ids(
        self,
        *,
        project: Project,
        query: str,
        limit: int,
        exclude_feature_id: int | None = None,
    ) -> list[int]:
        feature_ids = [
            entity_id
            for entity_id in self._search_entity_ids(
                project_id=project.id,
                query=query,
                entity_type="feature",
                limit=limit + 1 if exclude_feature_id is not None else limit,
            )
            if entity_id != exclude_feature_id
        ]
        return feature_ids[:limit]

    def search_task_ids(self, *, project: Project, query: str, limit: int) -> list[int]:
        return self._search_entity_ids(
            project_id=project.id,
            query=query,
            entity_type="task",
            limit=limit,
        )

    def _replace_memory(
        self,
        *,
        project_id: int,
        prefix: str,
        memory_text: str,
        metadata: dict[str, Any],
    ) -> None:
        current = [memory for memory in self.project_memories[project_id] if not memory.startswith(prefix)]
        current.append(memory_text)
        self.project_memories[project_id] = current
        current_entries = [
            entry
            for entry in self.project_memory_entries[project_id]
            if not entry["memory"].startswith(prefix)
        ]
        current_entries.append({"memory": memory_text, "metadata": metadata})
        self.project_memory_entries[project_id] = current_entries

    def _delete_memory(self, *, project_id: int, prefix: str) -> None:
        self.project_memories[project_id] = [
            memory for memory in self.project_memories[project_id] if not memory.startswith(prefix)
        ]
        self.project_memory_entries[project_id] = [
            entry
            for entry in self.project_memory_entries[project_id]
            if not entry["memory"].startswith(prefix)
        ]

    def _search_entity_ids(
        self,
        *,
        project_id: int,
        query: str,
        entity_type: str,
        limit: int,
    ) -> list[int]:
        if limit <= 0:
            return []

        lowered_query = query.strip().lower()
        if not lowered_query:
            return []

        ranked_entries: list[tuple[int, int]] = []
        for index, entry in enumerate(self.project_memory_entries.get(project_id, [])):
            metadata = entry["metadata"]
            if metadata.get("entity_type") != entity_type:
                continue
            memory_text = str(entry["memory"]).lower()
            score = memory_text.count(lowered_query)
            if score == 0:
                score = sum(1 for part in lowered_query.split() if part and part in memory_text)
            if score == 0:
                continue
            ranked_entries.append((score, index))

        ranked_entries.sort(key=lambda item: (-item[0], item[1]))

        entity_ids: list[int] = []
        for _, index in ranked_entries[:limit]:
            entity_id = self.project_memory_entries[project_id][index]["metadata"].get("entity_id")
            if isinstance(entity_id, int):
                entity_ids.append(entity_id)
        return entity_ids
