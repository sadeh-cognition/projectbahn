from __future__ import annotations

import json
import os

from django.contrib.auth import get_user_model

from ninja.testing import TestClient

import pytest
from model_bakery import baker
from django_llm_chat.models import LLMCall

from projects.api import api
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
        chat=baker.make("django_llm_chat.Chat"),
    )
    FeatureChatThread.objects.create(
        feature=feature,
        owner=other_user,
        title="Other thread",
        chat=baker.make("django_llm_chat.Chat"),
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
    thread = baker.make(FeatureChatThread, feature=feature, owner=user, chat=baker.make("django_llm_chat.Chat"))

    response = client.post(
        f"/features/{feature.id}/chat-threads/{thread.id}/messages/stream",
        json={"text": "How should we build login?"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


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
        chat=baker.make("django_llm_chat.Chat"),
    )

    response = client.post(
        f"/features/{feature.id}/chat-threads/{thread.id}/messages/stream",
        json={"text": "How should we build login?"},
        user=user,
    )

    assert response.status_code == 400
    assert "legacy API key entry" in response.json()["detail"]


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
        chat=baker.make("django_llm_chat.Chat"),
    )

    response = client.post(
        f"/features/{feature.id}/chat-threads/{thread.id}/messages/stream",
        json={"text": "Give me two short implementation suggestions for this feature."},
        user=user,
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/x-ndjson"
    events = [json.loads(line) for line in response.content.decode("utf-8").splitlines() if line.strip()]
    assert any(event["type"] == "chunk" for event in events)
    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["assistant_message"]["text"]
    assert FeatureChatMessage.objects.filter(thread=thread).count() == 2
    assert LLMCall.objects.exists()
