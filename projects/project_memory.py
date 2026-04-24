from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from projbahn import settings as app_settings
from projects.models import Feature, Project, ProjectLLMConfig, Task


class ProjectMemoryError(RuntimeError):
    pass


class ProjectMemoryStore(Protocol):
    def sync_feature(self, *, feature: Feature) -> None: ...

    def sync_task(self, *, task: Task) -> None: ...

    def delete_feature(self, *, feature: Feature) -> None: ...

    def delete_task(self, *, task: Task) -> None: ...

    def delete_project(self, *, project: Project) -> None: ...

    def build_feature_chat_context(self, *, feature: Feature, user_message: str) -> str: ...

    def search_feature_ids(
        self,
        *,
        project: Project,
        query: str,
        limit: int,
        exclude_feature_id: int | None = None,
    ) -> list[int]: ...

    def search_task_ids(
        self,
        *,
        project: Project,
        query: str,
        limit: int,
    ) -> list[int]: ...


@dataclass(slots=True)
class StoredProjectMemory:
    memory_id: str | None
    memory: str
    metadata: dict[str, Any]
    score: float | None = None


class Mem0ProjectMemoryStore:
    def __init__(self, memory_client: object | None = None) -> None:
        self._memory_client = memory_client

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
            memory_client=self._get_memory_client(project=feature.project),
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
            memory_client=self._get_memory_client(project=task.feature.project),
        )

    def delete_feature(self, *, feature: Feature) -> None:
        self._delete_entity_memories(
            project=feature.project,
            entity_type="feature",
            entity_id=feature.id,
            memory_client=self._get_memory_client(project=feature.project),
        )

    def delete_task(self, *, task: Task) -> None:
        self._delete_entity_memories(
            project=task.feature.project,
            entity_type="task",
            entity_id=task.id,
            memory_client=self._get_memory_client(project=task.feature.project),
        )

    def delete_project(self, *, project: Project) -> None:
        self._get_memory_client(project=project).delete_all(
            user_id=app_settings.mem0_settings.user_scope,
            agent_id=_build_project_agent_id(project.id),
        )

    def build_feature_chat_context(self, *, feature: Feature, user_message: str) -> str:
        memory_client = self._get_memory_client(project=feature.project)
        relevant_memories = self._search_project_memories(
            project=feature.project,
            query=f"{feature.name}\n{feature.description}\n{user_message}",
            memory_client=memory_client,
        )
        all_memories = self._list_project_memories(project=feature.project, memory_client=memory_client)
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
                project=project,
                query=query,
                entity_type="feature",
                limit=limit + 1 if exclude_feature_id is not None else limit,
            )
            if entity_id != exclude_feature_id
        ]
        return feature_ids[:limit]

    def search_task_ids(
        self,
        *,
        project: Project,
        query: str,
        limit: int,
    ) -> list[int]:
        return self._search_entity_ids(
            project=project,
            query=query,
            entity_type="task",
            limit=limit,
        )

    def _build_memory_client(self, *, project: Project) -> object:
        try:
            from mem0 import Memory
        except ImportError as exc:
            raise ProjectMemoryError("The mem0ai package is not installed.") from exc

        return Memory.from_config(_build_mem0_config(project=project))

    def _get_memory_client(self, *, project: Project) -> object:
        if self._memory_client is not None:
            return self._memory_client
        return self._build_memory_client(project=project)

    def _replace_entity_memory(
        self,
        *,
        project: Project,
        entity_type: str,
        entity_id: int,
        memory_text: str,
        metadata: dict[str, Any],
        memory_client: object,
    ) -> None:
        self._delete_entity_memories(
            project=project,
            entity_type=entity_type,
            entity_id=entity_id,
            memory_client=memory_client,
        )
        memory_client.add(
            memory_text,
            user_id=app_settings.mem0_settings.user_scope,
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
        memory_client: object,
    ) -> None:
        existing_memories = [
            memory
            for memory in self._list_project_memories(project=project, memory_client=memory_client)
            if memory.metadata.get("entity_type") == entity_type
            and memory.metadata.get("entity_id") == entity_id
        ]
        for memory in existing_memories:
            if memory.memory_id is None:
                continue
            memory_client.delete(memory.memory_id)

    def _list_project_memories(
        self, *, project: Project, memory_client: object
    ) -> list[StoredProjectMemory]:
        result = memory_client.get_all(
            filters=_build_project_filters(project_id=project.id),
            top_k=app_settings.mem0_settings.list_limit,
        )
        return _normalize_memories(result)

    def _search_project_memories(
        self,
        *,
        project: Project,
        query: str,
        memory_client: object,
        top_k: int | None = None,
    ) -> list[StoredProjectMemory]:
        if not query.strip():
            return []
        result = memory_client.search(
            query,
            filters=_build_project_filters(project_id=project.id),
            top_k=top_k or app_settings.mem0_settings.search_limit,
            threshold=0.0,
        )
        return _normalize_memories(result)

    def _search_entity_ids(
        self,
        *,
        project: Project,
        query: str,
        entity_type: str,
        limit: int,
    ) -> list[int]:
        if limit <= 0:
            return []

        memory_client = self._get_memory_client(project=project)
        memories = self._search_project_memories(
            project=project,
            query=query,
            memory_client=memory_client,
            top_k=max(app_settings.mem0_settings.search_limit, limit * 4),
        )

        entity_ids: list[int] = []
        seen_entity_ids: set[int] = set()
        for memory in memories:
            if memory.metadata.get("entity_type") != entity_type:
                continue
            entity_id = _coerce_optional_int(memory.metadata.get("entity_id"))
            if entity_id is None or entity_id in seen_entity_ids:
                continue
            entity_ids.append(entity_id)
            seen_entity_ids.add(entity_id)
            if len(entity_ids) >= limit:
                break
        return entity_ids


def get_project_memory_store() -> ProjectMemoryStore:
    return Mem0ProjectMemoryStore()


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


def build_feature_chat_project_context(*, feature: Feature, user_message: str) -> str:
    return get_project_memory_store().build_feature_chat_context(
        feature=feature,
        user_message=user_message,
    )


def _build_project_agent_id(project_id: int) -> str:
    return f"project-{project_id}"


def _build_project_filters(*, project_id: int) -> dict[str, Any]:
    return {
        "user_id": app_settings.mem0_settings.user_scope,
        "agent_id": _build_project_agent_id(project_id),
    }


def _build_mem0_config(*, project: Project) -> dict[str, Any]:
    llm_config: dict[str, Any] = {
        "provider": "lmstudio",
        "config": {
            "lmstudio_base_url": app_settings.mem0_settings.lmstudio_base_url,
            "temperature": 0.0,
        },
    }
    project_llm_config = ProjectLLMConfig.get_for_project(project)
    if project_llm_config is not None and project_llm_config.llm_name:
        llm_config["config"]["model"] = project_llm_config.llm_name

    embedder_config: dict[str, Any] = {
        "provider": "lmstudio",
        "config": {
            "lmstudio_base_url": app_settings.mem0_settings.lmstudio_base_url,
            "model": app_settings.mem0_settings.embedder_model,
            "embedding_dims": app_settings.mem0_settings.embedding_dims,
        },
    }

    return {
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": app_settings.mem0_settings.collection_name,
                "path": app_settings.mem0_settings.chroma_path,
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


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
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
