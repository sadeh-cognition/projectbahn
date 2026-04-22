from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings
from django.utils.module_loading import import_string

from projects.models import Feature, Project, Task


class ProjectMemoryError(RuntimeError):
    pass


class ProjectMemoryStore(Protocol):
    def sync_feature(self, *, feature: Feature) -> None: ...

    def sync_task(self, *, task: Task) -> None: ...

    def delete_feature(self, *, feature: Feature) -> None: ...

    def delete_task(self, *, task: Task) -> None: ...

    def delete_project(self, *, project: Project) -> None: ...

    def build_feature_chat_context(self, *, feature: Feature, user_message: str) -> str: ...


@dataclass(slots=True)
class StoredProjectMemory:
    memory_id: str | None
    memory: str
    metadata: dict[str, Any]
    score: float | None = None


class DisabledProjectMemoryStore:
    def sync_feature(self, *, feature: Feature) -> None:
        del feature

    def sync_task(self, *, task: Task) -> None:
        del task

    def delete_feature(self, *, feature: Feature) -> None:
        del feature

    def delete_task(self, *, task: Task) -> None:
        del task

    def delete_project(self, *, project: Project) -> None:
        del project

    def build_feature_chat_context(self, *, feature: Feature, user_message: str) -> str:
        del feature, user_message
        return ""


class Mem0ProjectMemoryStore:
    def __init__(self, memory_client: object | None = None) -> None:
        self._memory_client = memory_client or self._build_memory_client()

    def sync_feature(self, *, feature: Feature) -> None:
        self._replace_entity_memory(
            project=feature.project,
            entity_type="feature",
            entity_id=feature.id,
            memory_text=_serialize_feature_memory(feature),
            metadata={
                "project_id": feature.project_id,
                "entity_type": "feature",
                "entity_id": feature.id,
            },
        )

    def sync_task(self, *, task: Task) -> None:
        self._replace_entity_memory(
            project=task.feature.project,
            entity_type="task",
            entity_id=task.id,
            memory_text=_serialize_task_memory(task),
            metadata={
                "project_id": task.feature.project_id,
                "entity_type": "task",
                "entity_id": task.id,
                "feature_id": task.feature_id,
            },
        )

    def delete_feature(self, *, feature: Feature) -> None:
        self._delete_entity_memories(
            project=feature.project,
            entity_type="feature",
            entity_id=feature.id,
        )

    def delete_task(self, *, task: Task) -> None:
        self._delete_entity_memories(
            project=task.feature.project,
            entity_type="task",
            entity_id=task.id,
        )

    def delete_project(self, *, project: Project) -> None:
        self._memory_client.delete_all(
            user_id=settings.PROJBAHN_MEM0_USER_SCOPE,
            agent_id=_build_project_agent_id(project.id),
        )

    def build_feature_chat_context(self, *, feature: Feature, user_message: str) -> str:
        relevant_memories = self._search_project_memories(
            project=feature.project,
            query=f"{feature.name}\n{feature.description}\n{user_message}",
        )
        all_memories = self._list_project_memories(project=feature.project)
        seen_memory_texts: set[str] = set()
        sections: list[str] = []

        if relevant_memories:
            relevant_lines = ["Relevant project feature/task memories from mem0:"]
            for memory in relevant_memories:
                if memory.memory in seen_memory_texts:
                    continue
                relevant_lines.append(f"- {memory.memory}")
                seen_memory_texts.add(memory.memory)
            if len(relevant_lines) > 1:
                sections.append("\n".join(relevant_lines))

        if all_memories:
            all_lines = ["All saved project features/tasks from mem0:"]
            for memory in all_memories:
                if memory.memory in seen_memory_texts:
                    continue
                all_lines.append(f"- {memory.memory}")
                seen_memory_texts.add(memory.memory)
            if len(all_lines) > 1:
                sections.append("\n".join(all_lines))

        if not sections:
            return "No project feature/task memories are currently stored in mem0."

        return "\n\n".join(sections)

    def _build_memory_client(self) -> object:
        try:
            from mem0 import Memory
        except ImportError as exc:
            raise ProjectMemoryError(
                "mem0 is enabled but the mem0ai package is not installed."
            ) from exc

        return Memory.from_config(_build_mem0_config())

    def _replace_entity_memory(
        self,
        *,
        project: Project,
        entity_type: str,
        entity_id: int,
        memory_text: str,
        metadata: dict[str, Any],
    ) -> None:
        self._delete_entity_memories(
            project=project,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        self._memory_client.add(
            memory_text,
            user_id=settings.PROJBAHN_MEM0_USER_SCOPE,
            agent_id=_build_project_agent_id(project.id),
            metadata=metadata,
            infer=False,
        )

    def _delete_entity_memories(
        self,
        *,
        project: Project,
        entity_type: str,
        entity_id: int,
    ) -> None:
        existing_memories = [
            memory
            for memory in self._list_project_memories(project=project)
            if memory.metadata.get("entity_type") == entity_type
            and memory.metadata.get("entity_id") == entity_id
        ]
        for memory in existing_memories:
            if memory.memory_id is None:
                continue
            self._memory_client.delete(memory.memory_id)

    def _list_project_memories(self, *, project: Project) -> list[StoredProjectMemory]:
        result = self._memory_client.get_all(
            filters=_build_project_filters(project_id=project.id),
            top_k=settings.PROJBAHN_MEM0_LIST_LIMIT,
        )
        return _normalize_memories(result)

    def _search_project_memories(self, *, project: Project, query: str) -> list[StoredProjectMemory]:
        result = self._memory_client.search(
            query,
            filters=_build_project_filters(project_id=project.id),
            top_k=settings.PROJBAHN_MEM0_SEARCH_LIMIT,
            threshold=0.0,
        )
        return _normalize_memories(result)


def get_project_memory_store() -> ProjectMemoryStore:
    if not settings.PROJBAHN_MEM0_ENABLED:
        return DisabledProjectMemoryStore()

    store_class = import_string(settings.PROJBAHN_MEM0_STORE_CLASS)
    store = store_class()
    if not isinstance(store, DisabledProjectMemoryStore) and not hasattr(store, "build_feature_chat_context"):
        raise ProjectMemoryError("Configured project memory store does not implement the required interface.")
    return store


def sync_feature_memory(*, feature: Feature) -> None:
    get_project_memory_store().sync_feature(feature=feature)


def sync_task_memory(*, task: Task) -> None:
    get_project_memory_store().sync_task(task=task)


def delete_feature_memory(*, feature: Feature) -> None:
    get_project_memory_store().delete_feature(feature=feature)


def delete_task_memory(*, task: Task) -> None:
    get_project_memory_store().delete_task(task=task)


def delete_project_memories(*, project: Project) -> None:
    get_project_memory_store().delete_project(project=project)


def build_feature_chat_memory_context(*, feature: Feature, user_message: str) -> str:
    return get_project_memory_store().build_feature_chat_context(
        feature=feature,
        user_message=user_message,
    )


def _build_project_agent_id(project_id: int) -> str:
    return f"project-{project_id}"


def _build_project_filters(*, project_id: int) -> dict[str, Any]:
    return {
        "AND": [
            {"user_id": settings.PROJBAHN_MEM0_USER_SCOPE},
            {"agent_id": _build_project_agent_id(project_id)},
        ]
    }


def _build_mem0_config() -> dict[str, Any]:
    llm_config: dict[str, Any] = {
        "provider": "lmstudio",
        "config": {
            "lmstudio_base_url": settings.PROJBAHN_MEM0_LMSTUDIO_BASE_URL,
            "temperature": 0.0,
        },
    }
    if settings.PROJBAHN_MEM0_LLM_MODEL:
        llm_config["config"]["model"] = settings.PROJBAHN_MEM0_LLM_MODEL

    embedder_config: dict[str, Any] = {
        "provider": "lmstudio",
        "config": {
            "lmstudio_base_url": settings.PROJBAHN_MEM0_LMSTUDIO_BASE_URL,
            "embedding_dims": settings.PROJBAHN_MEM0_EMBEDDING_DIMS,
        },
    }
    if settings.PROJBAHN_MEM0_EMBEDDER_MODEL:
        embedder_config["config"]["model"] = settings.PROJBAHN_MEM0_EMBEDDER_MODEL

    return {
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": settings.PROJBAHN_MEM0_COLLECTION_NAME,
                "path": settings.PROJBAHN_MEM0_CHROMA_PATH,
            },
        },
        "llm": llm_config,
        "embedder": embedder_config,
    }


def _normalize_memories(result: Any) -> list[StoredProjectMemory]:
    if isinstance(result, dict):
        raw_memories = result.get("results", [])
    elif isinstance(result, list):
        raw_memories = result
    else:
        raw_memories = []

    normalized: list[StoredProjectMemory] = []
    for item in raw_memories:
        if not isinstance(item, dict):
            continue
        normalized.append(
            StoredProjectMemory(
                memory_id=_coerce_optional_str(item.get("id")),
                memory=str(item.get("memory", "")),
                metadata=_coerce_metadata(item.get("metadata")),
                score=_coerce_optional_float(item.get("score")),
            )
        )
    return normalized


def _coerce_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _serialize_feature_memory(feature: Feature) -> str:
    parent_feature_text = "none" if feature.parent_feature_id is None else str(feature.parent_feature_id)
    return (
        f"Feature #{feature.id}. "
        f"Parent feature id: {parent_feature_text}. "
        f"Name: {feature.name}. "
        f"Description: {feature.description.strip() or 'No description.'}"
    )


def _serialize_task_memory(task: Task) -> str:
    return (
        f"Task #{task.id}. "
        f"Feature id: {task.feature_id}. "
        f"Assignee username: {task.user.get_username()}. "
        f"Title: {task.title}. "
        f"Description: {task.description.strip() or 'No description.'} "
        f"Status: {task.status}."
    )
