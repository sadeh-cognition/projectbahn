from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import Client

import pytest
from model_bakery import baker

from projects.models import Feature, Project, Task

User = get_user_model()


@pytest.mark.django_db
def test_dashboard_shows_projects_entry_point_before_selection() -> None:
    client = Client()
    baker.make(Project, name="Platform", description="Core platform")

    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "View projects" in content
    assert "Select a project" in content
    assert "Project task table" not in content
    assert "Create project" not in content


@pytest.mark.django_db
def test_project_list_page_shows_projects_and_create_form() -> None:
    client = Client()
    project = baker.make(Project, name="Platform", description="Core platform")

    response = client.get("/projects/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Project list" in content
    assert "New project" in content
    assert project.name in content
    assert f"/?project_id={project.id}&tab=tasks" in content
    assert 'hx-post="/api/projects"' in content


@pytest.mark.django_db
def test_dashboard_renders_project_tasks_tab_by_default() -> None:
    client = Client()
    project = baker.make(Project, name="Platform", description="Core platform")
    feature = baker.make(
        Feature,
        project=project,
        parent_feature=None,
        name="Auth",
        description="Authentication feature",
    )
    user = baker.make(User, username="alex")
    baker.make(
        Task,
        feature=feature,
        user=user,
        title="Ship login page",
        description="Build the first usable login flow.",
        status="In progress",
    )

    response = client.get("/", {"project_id": project.id})

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Platform" in content
    assert "Ship login page" in content
    assert "Project task table" in content
    assert "Create top-level or nested features" not in content


@pytest.mark.django_db
def test_workspace_can_render_features_tab() -> None:
    client = Client()
    project = baker.make(Project, name="Platform", description="Core platform")
    feature = baker.make(
        Feature,
        project=project,
        parent_feature=None,
        name="Auth",
        description="Authentication feature",
    )
    user = baker.make(User, username="alex")

    response = client.get("/workspace/", {"project_id": project.id, "tab": "features"})

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Add feature" in content
    assert 'id="create-feature-dialog"' in content
    assert "Feature table" in content
    assert 'tab=project_settings' in content
    assert "Project settings" not in content
    assert "Save project" not in content
    assert "Project task table" not in content
    assert f'create-task-for-feature-{feature.id}' in content
    assert 'name="feature_id" value="' + str(feature.id) + '"' in content
    assert f"Create task for {feature.name}" in content
    assert user.username in content


@pytest.mark.django_db
def test_workspace_can_render_project_settings_tab() -> None:
    client = Client()
    project = baker.make(Project, name="Platform", description="Core platform")

    response = client.get("/workspace/", {"project_id": project.id, "tab": "project_settings"})

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Project settings" in content
    assert "Save project" in content
    assert "Create top-level or nested features" not in content


@pytest.mark.django_db
def test_workspace_reflects_api_driven_crud_and_task_filtering_flow() -> None:
    client = Client()
    user = baker.make(User, username="alex")

    create_project_response = client.post(
        "/api/projects",
        data=json.dumps({"name": "Delivery Hub", "description": "Track product delivery"}),
        content_type="application/json",
    )

    assert create_project_response.status_code == 200
    project = Project.objects.get(name="Delivery Hub")

    create_feature_response = client.post(
        "/api/features",
        data=json.dumps(
            {
                "project_id": project.id,
                "name": "Platform",
                "description": "Platform work",
                "parent_feature_id": None,
            },
        ),
        content_type="application/json",
    )

    assert create_feature_response.status_code == 200
    parent_feature = Feature.objects.get(project=project, name="Platform")

    nested_feature_response = client.post(
        "/api/features",
        data=json.dumps(
            {
                "project_id": project.id,
                "name": "Authentication",
                "description": "Nested auth work",
                "parent_feature_id": parent_feature.id,
            },
        ),
        content_type="application/json",
    )

    assert nested_feature_response.status_code == 200
    nested_feature = Feature.objects.get(project=project, name="Authentication")
    assert nested_feature.parent_feature_id == parent_feature.id

    create_task_response = client.post(
        "/api/tasks",
        data=json.dumps(
            {
                "title": "Ship login",
                "description": "Implement the login UI and API calls.",
                "feature_id": nested_feature.id,
                "user_id": user.id,
                "status": "In progress",
            },
        ),
        content_type="application/json",
    )

    assert create_task_response.status_code == 200
    task = Task.objects.get(feature=nested_feature, title="Ship login")
    assert task.description == "Implement the login UI and API calls."

    filtered_response = client.get(
        "/workspace/",
        {
            "project_id": project.id,
            "tab": "tasks",
            "search": "login",
            "status": "progress",
            "assignee": "alex",
            "sort_by": "title",
            "sort_dir": "asc",
        },
    )

    assert filtered_response.status_code == 200
    filtered_content = filtered_response.content.decode("utf-8")
    assert "Ship login" in filtered_content
    assert "Authentication" in filtered_content

    update_task_response = client.put(
        f"/api/tasks/{task.id}",
        data=json.dumps(
            {
                "title": "Ship login v2",
                "description": "Update the form validation and API wiring.",
                "feature_id": nested_feature.id,
                "user_id": user.id,
                "status": "Done",
            },
        ),
        content_type="application/json",
    )

    assert update_task_response.status_code == 200
    task.refresh_from_db()
    assert task.title == "Ship login v2"
    assert task.status == "Done"

    delete_task_response = client.delete(f"/api/tasks/{task.id}")
    delete_feature_response = client.delete(f"/api/features/{nested_feature.id}")
    delete_project_response = client.delete(f"/api/projects/{project.id}")

    assert delete_task_response.status_code == 204
    assert delete_feature_response.status_code == 204
    assert delete_project_response.status_code == 204
    assert not Task.objects.filter(id=task.id).exists()
    assert not Project.objects.filter(id=project.id).exists()
