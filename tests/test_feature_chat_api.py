from __future__ import annotations

import json
import os
import time

import dspy
from django.contrib.auth import get_user_model

from ninja.testing import TestClient

import pytest
from model_bakery import baker

from projbahn import settings as app_settings
from projbahn.dspy_settings import DSPySettings
from projects.api import api
from projects.feature_chat import (
    AgentActivityStreamStatusProvider,
    FeatureChatModule,
    FeatureChatProjectTools,
    build_conversation_history,
    build_feature_chat_module_inputs,
    build_lm_kwargs,
    build_stream_lm_kwargs,
    prepare_feature_chat_request,
)
from projects.models import Feature, FeatureChatMessage, FeatureChatThread, Project, ProjectLLMConfig, Task
from projects.observability import (
    configure_dspy_mlflow,
    mlflow_tracing_enabled,
    reset_dspy_mlflow_state,
)
from projects.project_memory import sync_feature_memory, sync_task_memory
from projects.schemas import (
    AgentActivityStreamEventSchema,
    FeatureChatThreadDetailSchema,
    FeatureChatThreadResponseSchema,
)

client = TestClient(api)
User = get_user_model()


@pytest.fixture
def user() -> User:
    return baker.make(User, username="alex")


@pytest.fixture
def feature() -> Feature:
    project = baker.make(Project, name="Platform", description="Core platform")
    return baker.make(
        Feature,
        project=project,
        parent_feature=None,
        name="Authentication",
        description="Authentication feature",
    )


@pytest.fixture(autouse=True)
def reset_mlflow_state() -> None:
    reset_dspy_mlflow_state()
    yield
    reset_dspy_mlflow_state()


@pytest.mark.django_db
def test_list_feature_chat_threads_requires_auth(feature: Feature) -> None:
    response = client.get(f"/features/{feature.id}/chat-threads")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


@pytest.mark.django_db
def test_create_and_get_feature_chat_thread(feature: Feature, user: User) -> None:
    create_response = client.post(
        f"/features/{feature.id}/chat-threads",
        json={"title": "Implementation review"},
        user=user,
    )

    assert create_response.status_code == 200
    thread = FeatureChatThreadResponseSchema.model_validate(create_response.json())
    assert thread.feature_id == feature.id
    assert thread.owner_id == user.id
    assert thread.message_count == 0

    get_response = client.get(f"/features/{feature.id}/chat-threads/{thread.id}", user=user)

    assert get_response.status_code == 200
    detail = FeatureChatThreadDetailSchema.model_validate(get_response.json())
    assert detail.thread.id == thread.id
    assert detail.messages == []


@pytest.mark.django_db
def test_list_feature_chat_threads_is_scoped_to_owner(feature: Feature, user: User) -> None:
    other_user = baker.make(User, username="zoe")
    own_thread = FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title="My thread",
    )
    FeatureChatThread.objects.create(
        feature=feature,
        owner=other_user,
        title="Other thread",
    )

    response = client.get(f"/features/{feature.id}/chat-threads", user=user)

    assert response.status_code == 200
    body = [FeatureChatThreadResponseSchema.model_validate(item) for item in response.json()]
    assert [item.id for item in body] == [own_thread.id]


@pytest.mark.django_db
def test_create_feature_chat_thread_rejects_blank_title(feature: Feature, user: User) -> None:
    response = client.post(
        f"/features/{feature.id}/chat-threads",
        json={"title": "   "},
        user=user,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Thread title is required."


@pytest.mark.django_db
def test_stream_feature_chat_requires_auth(feature: Feature, user: User) -> None:
    thread = baker.make(FeatureChatThread, feature=feature, owner=user)

    response = client.post(
        f"/features/{feature.id}/chat-threads/{thread.id}/messages/stream",
        json={"text": "How should we build login?"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


@pytest.mark.django_db
def test_stream_feature_chat_requires_project_llm_config(feature: Feature, user: User) -> None:
    thread = baker.make(FeatureChatThread, feature=feature, owner=user)

    response = client.post(
        f"/features/{feature.id}/chat-threads/{thread.id}/messages/stream",
        json={"text": "How should we build login?"},
        user=user,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Configure the project LLM before starting a feature chat."


@pytest.mark.django_db
def test_stream_feature_chat_rejects_legacy_api_key(feature: Feature, user: User) -> None:
    ProjectLLMConfig.objects.create(
        project=feature.project,
        provider="groq",
        llm_name="llama-3.1-8b-instant",
        api_key_hash="legacy-hash-only",
        encrypted_api_key="",
    )
    thread = FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title="Implementation review",
    )

    response = client.post(
        f"/features/{feature.id}/chat-threads/{thread.id}/messages/stream",
        json={"text": "How should we build login?"},
        user=user,
    )

    assert response.status_code == 400
    assert "legacy API key entry" in response.json()["detail"]


@pytest.mark.django_db
def test_build_lm_kwargs_passes_explicit_provider_for_slash_model_name(feature: Feature) -> None:
    config = ProjectLLMConfig.objects.create(
        project=feature.project,
        provider="openrouter",
        llm_name="qwen/qwen3.6-plus",
    )
    config.set_api_key("test-api-key")
    config.save(update_fields=["api_key_hash", "encrypted_api_key", "date_updated"])

    kwargs = build_lm_kwargs(config)

    assert kwargs["model"] == "qwen/qwen3.6-plus"
    assert kwargs["custom_llm_provider"] == "openrouter"
    assert kwargs["api_key"] == "test-api-key"


@pytest.mark.django_db
def test_build_stream_lm_kwargs_omits_dspy_cache_flag(feature: Feature) -> None:
    config = ProjectLLMConfig.objects.create(
        project=feature.project,
        provider="groq",
        llm_name="llama-3.1-8b-instant",
    )
    config.set_api_key("test-api-key")
    config.save(update_fields=["api_key_hash", "encrypted_api_key", "date_updated"])

    kwargs = build_stream_lm_kwargs(config)

    assert kwargs["model"] == "groq/llama-3.1-8b-instant"
    assert kwargs["custom_llm_provider"] == "groq"
    assert kwargs["api_key"] == "test-api-key"
    assert kwargs["cache"] is False


def test_mlflow_tracing_enabled_requires_flag_and_tracking_uri(monkeypatch) -> None:
    monkeypatch.setattr(
        app_settings,
        "dspy_settings",
        DSPySettings(
        mlflow_enabled=False,
        mlflow_tracking_uri="http://127.0.0.1:5000",
        ),
    )
    assert mlflow_tracing_enabled() is False

    monkeypatch.setattr(
        app_settings,
        "dspy_settings",
        DSPySettings(
            mlflow_enabled=True,
            mlflow_tracking_uri="   ",
        ),
    )
    assert mlflow_tracing_enabled() is False

    monkeypatch.setattr(
        app_settings,
        "dspy_settings",
        DSPySettings(
            mlflow_enabled=True,
            mlflow_tracking_uri="http://127.0.0.1:5000",
        ),
    )
    assert mlflow_tracing_enabled() is True


def test_configure_dspy_mlflow_sets_tracking_uri_experiment_and_autolog_once(monkeypatch) -> None:
    class FakeDSPyAutolog:
        def __init__(self) -> None:
            self.calls = 0

        def autolog(self) -> None:
            self.calls += 1

    class FakeMLflow:
        def __init__(self) -> None:
            self.tracking_uris: list[str] = []
            self.experiments: list[str] = []
            self.dspy = FakeDSPyAutolog()

        def set_tracking_uri(self, value: str) -> None:
            self.tracking_uris.append(value)

        def set_experiment(self, value: str) -> None:
            self.experiments.append(value)

    monkeypatch.setattr(
        app_settings,
        "dspy_settings",
        DSPySettings(
            mlflow_enabled=True,
            mlflow_tracking_uri="http://127.0.0.1:5000",
            mlflow_experiment_name="Projbahn DSPy",
        ),
    )
    fake_mlflow = FakeMLflow()

    assert configure_dspy_mlflow(mlflow_module=fake_mlflow) is True
    assert configure_dspy_mlflow(mlflow_module=fake_mlflow) is True
    assert fake_mlflow.tracking_uris == ["http://127.0.0.1:5000"]
    assert fake_mlflow.experiments == ["Projbahn DSPy"]
    assert fake_mlflow.dspy.calls == 1


def test_configure_dspy_mlflow_logs_when_tracking_uri_is_set_but_disabled(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        app_settings,
        "dspy_settings",
        DSPySettings(
            mlflow_enabled=False,
            mlflow_tracking_uri="http://127.0.0.1:5000",
            mlflow_experiment_name="Projbahn DSPy",
        ),
    )

    with caplog.at_level("INFO"):
        assert configure_dspy_mlflow() is False

    assert "PROJBAHN_DSPY_MLFLOW_ENABLED=true" in caplog.text


@pytest.mark.django_db
def test_build_feature_chat_module_inputs_returns_dspy_inputs(
    feature: Feature,
    user: User,
) -> None:
    thread = FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title="Implementation review",
    )

    module_inputs = build_feature_chat_module_inputs(
        thread=thread,
        conversation_history=dspy.History(
            messages=[{"user_message": "What exists already?", "assistant_reply": "Existing guidance"}]
        ),
        user_message="How should we build login?",
    )

    assert module_inputs == {
        "project_name": "Platform",
        "project_description": "Core platform",
        "feature_name": "Authentication",
        "feature_description": "Authentication feature",
        "conversation_history": dspy.History(
            messages=[{"user_message": "What exists already?", "assistant_reply": "Existing guidance"}]
        ),
        "user_message": "How should we build login?",
    }


@pytest.mark.django_db
def test_feature_chat_project_tools_search_other_features_returns_same_project_matches(
    feature: Feature,
) -> None:
    related_feature = baker.make(
        Feature,
        project=feature.project,
        parent_feature=feature,
        name="Authorization",
        description="Role and permission management",
    )
    baker.make(
        Feature,
        project=baker.make(Project),
        parent_feature=None,
        name="Billing",
        description="Stripe billing flows",
    )
    sync_feature_memory(feature=related_feature)
    tools = FeatureChatProjectTools(feature=feature)

    result = tools.search_other_features(query="role")

    assert "Other project features:" in result
    assert f"Feature {related_feature.id}: Authorization" in result
    assert "Authentication feature" not in result
    assert "Billing" not in result


@pytest.mark.django_db
def test_feature_chat_project_tools_search_other_features_uses_mem0_results(
    feature: Feature,
) -> None:
    baker.make(
        Feature,
        project=feature.project,
        parent_feature=feature,
        name="Authorization",
        description="Role and permission management",
    )
    tools = FeatureChatProjectTools(feature=feature)

    result = tools.search_other_features(query="role")

    assert result == "No other features matched 'role' in this project."


@pytest.mark.django_db
def test_feature_chat_project_tools_search_project_tasks_filters_to_current_project(
    feature: Feature,
    user: User,
) -> None:
    related_feature = baker.make(
        Feature,
        project=feature.project,
        parent_feature=None,
        name="Authorization",
        description="Role and permission management",
    )
    matching_task = baker.make(
        Task,
        feature=related_feature,
        user=user,
        title="Implement RBAC",
        description="Add role checks to endpoints",
        status="in_progress",
    )
    baker.make(
        Task,
        feature=baker.make(Feature, project=baker.make(Project)),
        user=user,
        title="Implement RBAC elsewhere",
        description="Should not appear",
        status="todo",
    )
    sync_task_memory(task=matching_task)
    tools = FeatureChatProjectTools(feature=feature)

    result = tools.search_project_tasks(query="RBAC", status="progress")

    assert "Project tasks:" in result
    assert f"Task {matching_task.id}: Implement RBAC" in result
    assert "feature=Authorization" in result
    assert "Implement RBAC elsewhere" not in result


@pytest.mark.django_db
def test_feature_chat_project_tools_search_project_tasks_uses_mem0_results(
    feature: Feature,
    user: User,
) -> None:
    related_feature = baker.make(
        Feature,
        project=feature.project,
        parent_feature=None,
        name="Authorization",
        description="Role and permission management",
    )
    baker.make(
        Task,
        feature=related_feature,
        user=user,
        title="Implement RBAC",
        description="Add role checks to endpoints",
        status="in_progress",
    )
    tools = FeatureChatProjectTools(feature=feature)

    result = tools.search_project_tasks(query="RBAC", status="progress")

    assert result == "No project tasks matched the supplied filters."


@pytest.mark.django_db
def test_feature_chat_module_uses_dspy_react_with_project_tools(feature: Feature) -> None:
    module = FeatureChatModule(feature=feature)

    assert isinstance(module.respond, dspy.ReAct)
    assert module.respond.max_iters == 6
    assert set(module.respond.tools) == {"search_other_features", "search_project_tasks", "finish"}


def test_agent_activity_stream_provider_formats_sanitized_start_event() -> None:
    class ToolInstance:
        name = "search_project_tasks"

    provider = AgentActivityStreamStatusProvider()

    message = provider.tool_start_status_message(
        ToolInstance(),
        {
            "query": "RBAC\nwith admin permissions",
            "status": "in_progress",
            "limit": 5,
        },
    )

    assert message is not None
    event = AgentActivityStreamEventSchema.model_validate(json.loads(message))
    assert event.type == "activity"
    assert event.status == "running"
    assert event.tool == "search_project_tasks"
    assert event.label == "Searching project tasks"
    assert event.detail == "query: RBAC with admin permissions, status: in_progress, limit: 5"
    assert event.step == 1


def test_agent_activity_stream_provider_formats_complete_event() -> None:
    class ToolInstance:
        name = "search_project_tasks"

    provider = AgentActivityStreamStatusProvider()

    provider.tool_start_status_message(ToolInstance(), {"query": "RBAC", "limit": 5})
    message = provider.tool_end_status_message(
        "Project tasks:\n"
        "- Task 1: Build roles [status=todo, feature=Auth, assignee=alex]. Description: Add RBAC\n"
        "- Task 2: Test roles [status=todo, feature=Auth, assignee=alex]. Description: Add coverage"
    )

    event = AgentActivityStreamEventSchema.model_validate(json.loads(message))
    assert event.type == "activity"
    assert event.status == "complete"
    assert event.tool == "search_project_tasks"
    assert event.label == "Found 2 matching tasks"
    assert event.detail is not None
    assert event.detail.startswith("Project tasks: elapsed: ")
    assert event.step == 1
    assert event.elapsed_ms is not None
    assert event.elapsed_ms >= 0


def test_agent_activity_stream_provider_formats_lm_events_with_elapsed_time() -> None:
    class LMInstance:
        model = "groq/llama-3.1-8b-instant"

    provider = AgentActivityStreamStatusProvider()

    start_message = provider.lm_start_status_message(LMInstance(), {})
    time.sleep(0.001)
    end_message = provider.lm_end_status_message({})

    start_event = AgentActivityStreamEventSchema.model_validate(json.loads(start_message))
    end_event = AgentActivityStreamEventSchema.model_validate(json.loads(end_message))
    assert start_event.type == "activity"
    assert start_event.status == "running"
    assert start_event.tool == "language_model"
    assert start_event.label == "Calling language model"
    assert start_event.detail == "model: groq/llama-3.1-8b-instant"
    assert start_event.step == 1
    assert end_event.type == "activity"
    assert end_event.status == "complete"
    assert end_event.tool == "language_model"
    assert end_event.label == "Language model finished"
    assert end_event.detail is not None
    assert end_event.detail.startswith("elapsed: ")
    assert end_event.step == 1
    assert end_event.elapsed_ms is not None
    assert end_event.elapsed_ms >= 0


@pytest.mark.django_db
def test_build_conversation_history_returns_dspy_history(feature: Feature, user: User) -> None:
    thread = FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title="Implementation review",
    )
    FeatureChatMessage.objects.create(
        thread=thread,
        role=FeatureChatMessage.Role.USER,
        text="How should login work?",
    )
    FeatureChatMessage.objects.create(
        thread=thread,
        role=FeatureChatMessage.Role.ASSISTANT,
        text="Start with session auth.",
    )

    history = build_conversation_history(thread)

    assert history == dspy.History(
        messages=[
            {
                "user_message": "How should login work?",
                "assistant_reply": "Start with session auth.",
            }
        ]
    )


@pytest.mark.django_db
def test_prepare_feature_chat_request_builds_dspy_module_inputs_without_persisting_user_message(
    feature: Feature,
    user: User,
) -> None:
    config = ProjectLLMConfig.objects.create(
        project=feature.project,
        provider="groq",
        llm_name="llama-3.1-8b-instant",
    )
    config.set_api_key("test-api-key")
    config.save(update_fields=["api_key_hash", "encrypted_api_key", "date_updated"])
    thread = FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title="Implementation review",
    )
    FeatureChatMessage.objects.create(
        thread=thread,
        role=FeatureChatMessage.Role.ASSISTANT,
        text="Existing guidance",
    )

    user_text, returned_config, module_inputs = prepare_feature_chat_request(
        thread=thread,
        text="How should we build login?",
        user=user,
    )

    assert user_text == "How should we build login?"
    assert returned_config.id == config.id
    assert module_inputs["project_name"] == "Platform"
    assert module_inputs["project_description"] == "Core platform"
    assert module_inputs["feature_name"] == "Authentication"
    assert module_inputs["feature_description"] == "Authentication feature"
    assert module_inputs["conversation_history"] == dspy.History(
        messages=[{"user_message": "", "assistant_reply": "Existing guidance"}]
    )
    assert module_inputs["user_message"] == "How should we build login?"
    assert FeatureChatMessage.objects.filter(thread=thread, role=FeatureChatMessage.Role.USER).count() == 0


@pytest.mark.django_db
def test_create_feature_chat_assistant_message_persists_metadata(feature: Feature, user: User) -> None:
    config = ProjectLLMConfig.objects.create(
        project=feature.project,
        provider="groq",
        llm_name="llama-3.1-8b-instant",
    )
    thread = FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title="Implementation review",
    )

    assistant_message = thread.create_feature_chat_assistant_message(
        config=config,
        assistant_text="  Add auth middleware first.  ",
    )

    assert assistant_message.role == FeatureChatMessage.Role.ASSISTANT
    assert assistant_message.text == "Add auth middleware first."
    assert assistant_message.metadata == {
        "provider": "groq",
        "llm_name": "groq/llama-3.1-8b-instant",
    }


@pytest.mark.django_db
@pytest.mark.live_llm
def test_stream_feature_chat_returns_ndjson_and_persists_messages(feature: Feature, user: User) -> None:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY is not configured")

    config = ProjectLLMConfig.objects.create(
        project=feature.project,
        provider="groq",
        llm_name="llama-3.1-8b-instant",
    )
    config.set_api_key(api_key)
    config.save(update_fields=["api_key_hash", "encrypted_api_key", "date_updated"])
    thread = FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title="Implementation review",
    )

    response = client.post(
        f"/features/{feature.id}/chat-threads/{thread.id}/messages/stream",
        json={"text": "Give me two short implementation suggestions for this feature."},
        user=user,
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/x-ndjson"
    assert response["Cache-Control"] == "no-cache"
    assert response["X-Accel-Buffering"] == "no"
    events = [
        AgentActivityStreamEventSchema.model_validate(json.loads(line))
        for line in response.content.decode("utf-8").splitlines()
        if line.strip()
    ]
    assert events[0].type == "activity"
    assert events[0].label == "Reviewing feature context"
    assert any(event.type == "chunk" for event in events)
    done_event = next(event for event in events if event.type == "done")
    assert done_event.assistant_message is not None
    assert done_event.assistant_message.text
    assert done_event.thread is not None
    assert done_event.thread.id == thread.id
    assert done_event.llm_call_id is None
    assert FeatureChatMessage.objects.filter(thread=thread).count() == 2


@pytest.mark.django_db
def test_stream_feature_chat_does_not_persist_orphaned_user_message_on_stream_failure(
    feature: Feature, user: User
) -> None:
    config = ProjectLLMConfig.objects.create(
        project=feature.project,
        provider="invalid-provider",
        llm_name="invalid-model",
    )
    config.set_api_key("test-api-key")
    config.save(update_fields=["api_key_hash", "encrypted_api_key", "date_updated"])
    thread = FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title="Implementation review",
    )

    response = client.post(
        f"/features/{feature.id}/chat-threads/{thread.id}/messages/stream",
        json={"text": "Give me implementation guidance."},
        user=user,
    )
    events = [
        AgentActivityStreamEventSchema.model_validate(json.loads(line))
        for line in response.content.decode("utf-8").splitlines()
        if line.strip()
    ]

    assert response.status_code == 200
    assert events[0].type == "activity"
    assert events[0].label == "Reviewing feature context"
    assert events[-1].type == "error"
    assert events[-1].detail
    assert FeatureChatMessage.objects.filter(thread=thread).count() == 0
