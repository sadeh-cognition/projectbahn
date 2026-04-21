from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import dspy
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

from projects.models import (
    Feature,
    FeatureChatMessage,
    FeatureChatThread,
    ProjectLLMConfig,
)


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


def create_feature_chat_thread(
    *, feature: Feature, user: object, title: str
) -> FeatureChatThread:
    cleaned_title = title.strip()
    if not cleaned_title:
        raise FeatureChatConfigurationError("Thread title is required.")
    return FeatureChatThread.objects.create(
        feature=feature,
        owner=user,
        title=cleaned_title,
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
        raise FeatureChatConfigurationError(
            "Configure the project LLM before starting a feature chat."
        ) from exc

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


def build_lm_kwargs(config: ProjectLLMConfig) -> dict[str, Any]:
    return {
        "model": build_model_name(config),
        "api_key": config.get_api_key(),
        "temperature": 0.2,
        "cache": True,
        "max_tokens": 1200,
        "custom_llm_provider": config.provider,
    }


def build_stream_lm_kwargs(config: ProjectLLMConfig) -> dict[str, Any]:
    kwargs = build_lm_kwargs(config).copy()
    kwargs["cache"] = False
    return kwargs


def build_feature_chat_module_inputs(
    *,
    thread: FeatureChatThread,
    conversation_history: str,
    user_message: str,
) -> dict[str, str]:
    return {
        "project_name": thread.feature.project.name,
        "project_description": thread.feature.project.description,
        "feature_name": thread.feature.name,
        "feature_description": thread.feature.description,
        "conversation_history": conversation_history,
        "user_message": user_message,
    }


def prepare_feature_chat_request(
    *, thread: FeatureChatThread, text: str, user: object
) -> tuple[str, ProjectLLMConfig, dict[str, str]]:
    del user
    cleaned_text = text.strip()
    if not cleaned_text:
        raise FeatureChatConfigurationError("Message text is required.")

    config = get_project_llm_config(thread.feature)
    module_inputs = build_feature_chat_module_inputs(
        thread=thread,
        conversation_history=build_history_text(thread),
        user_message=cleaned_text,
    )
    return cleaned_text, config, module_inputs


def iter_feature_chat_response_text(
    *, config: ProjectLLMConfig, module_inputs: dict[str, str]
) -> Iterator[str]:
    lm = dspy.LM(**build_stream_lm_kwargs(config))
    module = FeatureChatModule()
    stream_module = dspy.streamify(
        module,
        stream_listeners=[
            dspy.streaming.StreamListener(signature_field_name="assistant_reply"),
        ],
        async_streaming=False,
    )
    final_prediction: dspy.Prediction | None = None
    yielded_chunk = False

    with dspy.context(lm=lm):
        for value in stream_module(**module_inputs):
            if isinstance(value, dspy.streaming.StreamResponse):
                if value.chunk:
                    yielded_chunk = True
                    yield value.chunk
                continue
            if isinstance(value, dspy.Prediction):
                final_prediction = value

    if final_prediction is None:
        raise RuntimeError("Feature chat stream completed without a final prediction.")
    if not yielded_chunk and final_prediction.assistant_reply:
        yield final_prediction.assistant_reply


def create_feature_chat_assistant_message(
    *,
    thread: FeatureChatThread,
    config: ProjectLLMConfig,
    assistant_text: str,
) -> FeatureChatMessage:
    assistant_message = FeatureChatMessage.objects.create(
        thread=thread,
        role=FeatureChatMessage.Role.ASSISTANT,
        text=assistant_text.strip(),
        metadata={
            "provider": config.provider,
            "llm_name": build_model_name(config),
        },
    )
    thread.save(update_fields=["date_updated"])
    return assistant_message


@transaction.atomic
def create_feature_chat_exchange(
    *,
    thread: FeatureChatThread,
    config: ProjectLLMConfig,
    user_text: str,
    assistant_text: str,
) -> tuple[FeatureChatMessage, FeatureChatMessage]:
    user_message = FeatureChatMessage.objects.create(
        thread=thread,
        role=FeatureChatMessage.Role.USER,
        text=user_text.strip(),
    )
    assistant_message = create_feature_chat_assistant_message(
        thread=thread,
        config=config,
        assistant_text=assistant_text,
    )
    return user_message, assistant_message


@transaction.atomic
def generate_feature_chat_reply(
    *, thread: FeatureChatThread, text: str, user: object
) -> FeatureChatReply:
    del user
    cleaned_text = text.strip()
    if not cleaned_text:
        raise FeatureChatConfigurationError("Message text is required.")
    config = get_project_llm_config(thread.feature)
    lm = dspy.LM(**build_lm_kwargs(config))
    module = FeatureChatModule()
    with dspy.context(lm=lm):
        prediction = module(
            project_name=thread.feature.project.name,
            project_description=thread.feature.project.description,
            feature_name=thread.feature.name,
            feature_description=thread.feature.description,
            conversation_history=build_history_text(thread),
            user_message=cleaned_text,
        )

    user_message, assistant_message = create_feature_chat_exchange(
        thread=thread,
        config=config,
        user_text=cleaned_text,
        assistant_text=prediction.assistant_reply,
    )
    return FeatureChatReply(
        user_message=user_message,
        assistant_message=assistant_message,
        llm_call_id=None,
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
