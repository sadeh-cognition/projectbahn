from __future__ import annotations

from django.core.management import call_command

import pytest
from model_bakery import baker

from projects.models import Feature, Project, Task
from tests.mem0_backends import RecordingProjectMemoryStore


@pytest.mark.django_db
def test_backfill_mem0_syncs_existing_features_and_tasks(django_user_model, capsys) -> None:
    user = baker.make(django_user_model)
    project = baker.make(Project)
    root_feature = baker.make(
        Feature,
        project=project,
        parent_feature=None,
        name="Platform",
        description="Core platform work",
    )
    child_feature = baker.make(
        Feature,
        project=project,
        parent_feature=root_feature,
        name="Authentication",
        description="Identity and access",
    )
    first_task = baker.make(
        Task,
        feature=root_feature,
        user=user,
        title="Document platform scope",
        description="Summarize the current roadmap.",
        status="Todo",
    )
    second_task = baker.make(
        Task,
        feature=child_feature,
        user=user,
        title="Ship login flow",
        description="Implement login API and UI.",
        status="In progress",
    )

    call_command("backfill_mem0")

    captured = capsys.readouterr()
    assert captured.out.strip() == "Synced 2 features and 2 tasks to mem0 (4 total)."
    assert RecordingProjectMemoryStore.synced_features == [
        {
            "project_id": project.id,
            "feature_id": root_feature.id,
            "memory": f"feature:{root_feature.id}:Platform:Core platform work",
        },
        {
            "project_id": project.id,
            "feature_id": child_feature.id,
            "memory": f"feature:{child_feature.id}:Authentication:Identity and access",
        },
    ]
    assert RecordingProjectMemoryStore.synced_tasks == [
        {
            "project_id": project.id,
            "task_id": first_task.id,
            "memory": f"task:{first_task.id}:Document platform scope:Todo",
        },
        {
            "project_id": project.id,
            "task_id": second_task.id,
            "memory": f"task:{second_task.id}:Ship login flow:In progress",
        },
    ]
    assert RecordingProjectMemoryStore.project_memories[project.id] == [
        f"feature:{root_feature.id}:Platform:Core platform work",
        f"feature:{child_feature.id}:Authentication:Identity and access",
        f"task:{first_task.id}:Document platform scope:Todo",
        f"task:{second_task.id}:Ship login flow:In progress",
    ]


@pytest.mark.django_db
def test_backfill_mem0_is_dry_run(django_user_model, capsys) -> None:
    user = baker.make(django_user_model)
    project = baker.make(Project)
    feature = baker.make(Feature, project=project, parent_feature=None)
    baker.make(Task, feature=feature, user=user)

    call_command("backfill_mem0", "--dry-run")

    captured = capsys.readouterr()
    assert captured.out.strip() == "Would sync 1 features and 1 tasks to mem0 (2 total)."
    assert RecordingProjectMemoryStore.synced_features == []
    assert RecordingProjectMemoryStore.synced_tasks == []
    assert RecordingProjectMemoryStore.project_memories == {}
