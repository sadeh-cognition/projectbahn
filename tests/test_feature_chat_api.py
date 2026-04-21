from __future__ import annotations

import json
import os

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from ninja.testing import TestClient

import pytest
from model_bakery import baker

from projects.api import api
from projects.feature_chat import (
    build_feature_chat_module_inputs,
    build_lm_kwargs,
    build_stream_lm_kwargs,
    create_feature_chat_assistant_message,
    prepare_feature_chat_request,
)
from projects.models import Feature, FeatureChatMessage, FeatureChatThread, Project, ProjectLLMConfig
from projects.schemas import FeatureChatThreadDetailSchema, FeatureChatThreadResponseSchema

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
        conversation_history="Assistant: Existing guidance",
        user_message="How should we build login?",
    )

    assert module_inputs == {
        "project_name": "Platform",
        "project_description": "Core platform",
        "feature_name": "Authentication",
        "feature_description": "Authentication feature",
        "conversation_history": "Assistant: Existing guidance",
        "user_message": "How should we build login?",
    }


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
    assert module_inputs["conversation_history"] == "Assistant: Existing guidance"
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

    assistant_message = create_feature_chat_assistant_message(
        thread=thread,
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
    events = [json.loads(line) for line in response.content.decode("utf-8").splitlines() if line.strip()]
    assert any(event["type"] == "chunk" for event in events)
    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["assistant_message"]["text"]
    assert isinstance(done_event["assistant_message"]["date_created"], str)
    assert isinstance(done_event["thread"]["date_created"], str)
    assert FeatureChatThreadResponseSchema.model_validate(done_event["thread"]).id == thread.id
    assert done_event["llm_call_id"] is None
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

    with pytest.raises((ImproperlyConfigured, RuntimeError, ValueError)):
        client.post(
            f"/features/{feature.id}/chat-threads/{thread.id}/messages/stream",
            json={"text": "Give me implementation guidance."},
            user=user,
        )
    assert FeatureChatMessage.objects.filter(thread=thread).count() == 0
