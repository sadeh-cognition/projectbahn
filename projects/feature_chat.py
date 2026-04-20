from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import dspy
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django_llm_chat.dspy_chat import DSPyChat

from projects.models import Feature, FeatureChatMessage, FeatureChatThread, ProjectLLMConfig


class FeatureChatConfigurationError(ValueError):
    pass


class FeatureChatSignature(dspy.Signature):
    """Answer questions about a software project feature with concise, implementation-focused guidance."""

    project_name: str = dspy.InputField()
    project_description: str = dspy.InputField()
    feature_name: str = dspy.InputField()
    feature_description: str = dspy.InputField()
    conversation_history: str = dspy.InputField()
    user_message: str = dspy.InputField()
    assistant_reply: str = dspy.OutputField()


class FeatureChatModule(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.respond = dspy.Predict(FeatureChatSignature)

    def forward(
        self,
        *,
        project_name: str,
        project_description: str,
        feature_name: str,
        feature_description: str,
        conversation_history: str,
        user_message: str,
    ) -> dspy.Prediction:
        return self.respond(
            project_name=project_name,
            project_description=project_description,
            feature_name=feature_name,
            feature_description=feature_description,
            conversation_history=conversation_history,
            user_message=user_message,
        )


@dataclass(slots=True)
class FeatureChatReply:
    user_message: FeatureChatMessage
    assistant_message: FeatureChatMessage
    llm_call_id: int | None


def create_feature_chat_thread(*, feature: Feature, user: object, title: str) -> FeatureChatThread:
    cleaned_title = title.strip()
    if not cleaned_title:
        raise FeatureChatConfigurationError("Thread title is required.")
    dspy_chat = DSPyChat.create(project=None)
    return FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title=cleaned_title,
        chat=dspy_chat.chat_db_model,
    )


def list_thread_messages(thread: FeatureChatThread) -> list[FeatureChatMessage]:
    return list(thread.messages.order_by("date_created", "id"))


def build_history_text(thread: FeatureChatThread) -> str:
    messages = list_thread_messages(thread)
    if not messages:
        return "No previous messages."
    return "\n".join(f"{message.role.title()}: {message.text}" for message in messages)


def get_project_llm_config(feature: Feature) -> ProjectLLMConfig:
    try:
        config = feature.project.llm_config
    except ObjectDoesNotExist as exc:
        raise FeatureChatConfigurationError("Configure the project LLM before starting a feature chat.") from exc

    if not config.provider or not config.llm_name:
        raise FeatureChatConfigurationError("Project LLM config is incomplete.")
    if config.api_key_requires_reentry:
        raise FeatureChatConfigurationError(
            "This project has a legacy API key entry. Re-save the API key in project settings before chatting."
        )
    if not config.api_key_usable:
        raise FeatureChatConfigurationError("Project LLM API key is missing.")
    return config


def build_model_name(config: ProjectLLMConfig) -> str:
    if "/" in config.llm_name:
        return config.llm_name
    return f"{config.provider}/{config.llm_name}"


@transaction.atomic
def generate_feature_chat_reply(*, thread: FeatureChatThread, text: str, user: object) -> FeatureChatReply:
    cleaned_text = text.strip()
    if not cleaned_text:
        raise FeatureChatConfigurationError("Message text is required.")
    config = get_project_llm_config(thread.feature)
    user_message = FeatureChatMessage.objects.create(
        thread=thread,
        role=FeatureChatMessage.Role.USER,
        text=cleaned_text,
    )
    dspy_chat = DSPyChat.from_db(thread.chat)
    lm = dspy_chat.as_lm(
        model=build_model_name(config),
        user=user,
        use_cache=True,
        api_key=config.get_api_key(),
        temperature=0.2,
        max_tokens=1200,
    )
    module = FeatureChatModule()
    with dspy.context(lm=lm):
        prediction = module(
            project_name=thread.feature.project.name,
            project_description=thread.feature.project.description,
            feature_name=thread.feature.name,
            feature_description=thread.feature.description,
            conversation_history=build_history_text(thread),
            user_message=user_message.text,
        )

    assistant_text = str(getattr(prediction, "assistant_reply", "")).strip()
    assistant_message = FeatureChatMessage.objects.create(
        thread=thread,
        role=FeatureChatMessage.Role.ASSISTANT,
        text=assistant_text,
        llm_call_id=dspy_chat.llm_call.id if dspy_chat.llm_call is not None else None,
    )
    if dspy_chat.llm_call is not None:
        user_message.llm_call = dspy_chat.llm_call
        user_message.save(update_fields=["llm_call", "date_updated"])

    thread.save(update_fields=["date_updated"])
    return FeatureChatReply(
        user_message=user_message,
        assistant_message=assistant_message,
        llm_call_id=dspy_chat.llm_call.id if dspy_chat.llm_call is not None else None,
    )


def serialize_thread(thread: FeatureChatThread) -> dict[str, Any]:
    return {
        "id": thread.id,
        "feature_id": thread.feature_id,
        "owner_id": thread.owner_id,
        "owner_username": thread.owner.get_username(),
        "title": thread.title,
        "date_created": thread.date_created,
        "date_updated": thread.date_updated,
        "message_count": thread.messages.count(),
    }


def serialize_message(message: FeatureChatMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "text": message.text,
        "date_created": message.date_created,
        "metadata": message.metadata,
    }
