from __future__ import annotations

from dataclasses import dataclass

from projects.models import Feature, Task
from projects.project_memory import get_project_memory_store


@dataclass(frozen=True)
class Mem0BackfillResult:
    synced_feature_count: int
    synced_task_count: int

    @property
    def synced_count(self) -> int:
        return self.synced_feature_count + self.synced_task_count


def backfill_mem0(*, dry_run: bool = False) -> Mem0BackfillResult:
    features = list(Feature.get_all_with_relations_ordered())
    tasks = list(Task.get_base_queryset_with_relations().order_by("id"))
    result = Mem0BackfillResult(
        synced_feature_count=len(features),
        synced_task_count=len(tasks),
    )

    if dry_run:
        return result

    memory_store = get_project_memory_store()
    for feature in features:
        memory_store.sync_feature(feature=feature)
    for task in tasks:
        memory_store.sync_task(task=task)

    return result
