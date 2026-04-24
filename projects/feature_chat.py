from dataclasses import dataclass
from typing import Any, Iterator

import dspy
from django.db import transaction

from projbahn import settings as app_settings
from projects.models import (
    Feature,
    FeatureChatMessage,
    FeatureChatThread,
    ProjectLLMConfig,
    Task,
)
from projects.project_memory import build_feature_chat_project_context, get_project_memory_store


class FeatureChatConfigurationError(ValueError):
    pass


class FeatureChatSignature(dspy.Signature):
    """Answer questions about a software project feature with concise, implementation-focused guidance.

    Use the available tools to inspect other project features and tasks when the user needs cross-project context.
    """

    project_name: str = dspy.InputField()
    project_description: str = dspy.InputField()
    feature_name: str = dspy.InputField()
    feature_description: str = dspy.InputField()
    project_context: str = dspy.InputField()
    conversation_history: dspy.History = dspy.InputField()
    user_message: str = dspy.InputField()
    assistant_reply: str = dspy.OutputField()


class FeatureChatModule(dspy.Module):
    def __init__(self, *, feature: Feature) -> None:
        super().__init__()
        self.project_tools = FeatureChatProjectTools(feature=feature)
        self.respond = dspy.ReAct(
            FeatureChatSignature,
            tools=[
                self.project_tools.search_other_features,
                self.project_tools.search_project_tasks,
            ],
            max_iters=6,
        )

    def forward(
        self,
        *,
        project_name: str,
        project_description: str,
        feature_name: str,
        feature_description: str,
        project_context: str,
        conversation_history: dspy.History,
        user_message: str,
    ) -> dspy.Prediction:
        return self.respond(
            project_name=project_name,
            project_description=project_description,
            feature_name=feature_name,
            feature_description=feature_description,
            project_context=project_context,
            conversation_history=conversation_history,
            user_message=user_message,
        )


class FeatureChatProjectTools:
    def __init__(self, *, feature: Feature) -> None:
        self.feature = feature
        self.memory_store = get_project_memory_store()

    def search_other_features(self, query: str = "", limit: int = 5) -> str:
        """Search other features in the current project using mem0 similarity search."""
        cleaned_limit = max(1, min(limit, 10))
        cleaned_query = query.strip()
        if cleaned_query:
            feature_ids = self.memory_store.search_feature_ids(
                project=self.feature.project,
                query=cleaned_query,
                limit=cleaned_limit,
                exclude_feature_id=self.feature.id,
            )
            features = self._get_features_in_order(feature_ids)
        else:
            queryset = Feature.get_features_for_project_with_relations(self.feature.project_id).exclude(
                id=self.feature.id
            )
            features = list(queryset.order_by("id")[:cleaned_limit])
        if not features:
            if cleaned_query:
                return f"No other features matched '{cleaned_query}' in this project."
            return "No other features are available in this project."

        lines = ["Other project features:"]
        for feature in features:
            parent = (
                f", parent_feature_id={feature.parent_feature_id}"
                if feature.parent_feature_id is not None
                else ""
            )
            lines.append(
                f"- Feature {feature.id}: {feature.name}{parent}. Description: {feature.description}"
            )
        return "\n".join(lines)

    def search_project_tasks(
        self,
        query: str = "",
        feature_name: str = "",
        status: str = "",
        assignee: str = "",
        limit: int = 5,
    ) -> str:
        """Search tasks in the current project using mem0 similarity plus structured filters."""
        cleaned_limit = max(1, min(limit, 10))
        cleaned_feature_name = feature_name.strip()
        cleaned_status = status.strip()
        cleaned_assignee = assignee.strip()
        search_query = self._build_task_search_query(
            query=query.strip(),
            feature_name=cleaned_feature_name,
            status=cleaned_status,
            assignee=cleaned_assignee,
        )

        if search_query:
            task_ids = self.memory_store.search_task_ids(
                project=self.feature.project,
                query=search_query,
                limit=cleaned_limit,
            )
            tasks = self._get_tasks_in_order(
                task_ids,
                feature_name=cleaned_feature_name,
                status=cleaned_status,
                assignee=cleaned_assignee,
            )
        else:
            queryset = Task.get_base_queryset_with_relations().filter(feature__project_id=self.feature.project_id)
            tasks = list(queryset.order_by("-date_updated", "-id")[:cleaned_limit])
        if not tasks:
            return "No project tasks matched the supplied filters."

        lines = ["Project tasks:"]
        for task in tasks:
            lines.append(
                f"- Task {task.id}: {task.title} [status={task.status}, feature={task.feature.name}, "
                f"assignee={task.user.get_username()}]. Description: {task.description}"
            )
        return "\n".join(lines)

    def _build_task_search_query(
        self,
        *,
        query: str,
        feature_name: str,
        status: str,
        assignee: str,
    ) -> str:
        parts: list[str] = []
        if query:
            parts.append(query)
        if feature_name:
            parts.append(f"Feature: {feature_name}")
        if status:
            parts.append(f"Status: {status}")
        if assignee:
            parts.append(f"Assignee: {assignee}")
        return "\n".join(parts)

    def _get_features_in_order(self, feature_ids: list[int]) -> list[Feature]:
        if not feature_ids:
            return []

        features_by_id = {
            feature.id: feature
            for feature in Feature.get_features_for_project_with_relations(self.feature.project_id)
            .filter(id__in=feature_ids)
            .exclude(id=self.feature.id)
        }
        return [features_by_id[feature_id] for feature_id in feature_ids if feature_id in features_by_id]

    def _get_tasks_in_order(
        self,
        task_ids: list[int],
        *,
        feature_name: str,
        status: str,
        assignee: str,
    ) -> list[Task]:
        if not task_ids:
            return []

        queryset = Task.get_base_queryset_with_relations().filter(
            feature__project_id=self.feature.project_id,
            id__in=task_ids,
        )
        if feature_name:
            queryset = queryset.filter(feature__name__icontains=feature_name)
        if status:
            queryset = queryset.filter(status__icontains=status)
        if assignee:
            queryset = queryset.filter(user__username__icontains=assignee)

        tasks_by_id = {task.id: task for task in queryset}
        return [tasks_by_id[task_id] for task_id in task_ids if task_id in tasks_by_id]


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
    return FeatureChatThread.create_thread(
        feature=feature,
        owner=user,
        title=cleaned_title,
    )


def build_conversation_history(thread: FeatureChatThread) -> dspy.History:
    messages = thread.list_thread_messages()
    history_messages: list[dict[str, str]] = []
    pending_user_message: str | None = None

    for message in messages:
        if message.role == FeatureChatMessage.Role.USER:
            pending_user_message = message.text
            continue

        history_messages.append(
            {
                "user_message": pending_user_message or "",
                "assistant_reply": message.text,
            }
        )
        pending_user_message = None

    if pending_user_message is not None:
        history_messages.append(
            {
                "user_message": pending_user_message,
                "assistant_reply": "",
            }
        )

    return dspy.History(messages=history_messages)


def build_model_name(config: ProjectLLMConfig) -> str:
    if "/" in config.llm_name:
        return config.llm_name
    return f"{config.provider}/{config.llm_name}"


def build_lm_kwargs(config: ProjectLLMConfig) -> dict[str, Any]:
    return {
        "model": build_model_name(config),
        "api_key": config.get_api_key(),
        "temperature": app_settings.dspy_settings.temperature,
        "cache": app_settings.dspy_settings.cache_enabled,
        "max_tokens": app_settings.dspy_settings.max_tokens,
        "custom_llm_provider": config.provider,
    }


def build_stream_lm_kwargs(config: ProjectLLMConfig) -> dict[str, Any]:
    kwargs = build_lm_kwargs(config).copy()
    kwargs["cache"] = False
    return kwargs


def build_feature_chat_module_inputs(
    *,
    thread: FeatureChatThread,
    project_context: str,
    conversation_history: dspy.History,
    user_message: str,
) -> dict[str, Any]:
    return {
        "project_name": thread.feature.project.name,
        "project_description": thread.feature.project.description,
        "feature_name": thread.feature.name,
        "feature_description": thread.feature.description,
        "project_context": project_context,
        "conversation_history": conversation_history,
        "user_message": user_message,
    }


def prepare_feature_chat_request(
    *,
    thread: FeatureChatThread,
    text: str,
    user: object,
    project_context: str | None = None,
) -> tuple[str, ProjectLLMConfig, dict[str, Any]]:
    del user
    cleaned_text = text.strip()
    if not cleaned_text:
        raise FeatureChatConfigurationError("Message text is required.")

    config = thread.feature.project.get_project_llm_config()
    module_inputs = build_feature_chat_module_inputs(
        thread=thread,
        project_context=project_context
        if project_context is not None
        else build_feature_chat_project_context(
            feature=thread.feature,
            user_message=cleaned_text,
        ),
        conversation_history=build_conversation_history(thread),
        user_message=cleaned_text,
    )
    return cleaned_text, config, module_inputs


def iter_feature_chat_response_text(
    *, feature: Feature, config: ProjectLLMConfig, module_inputs: dict[str, Any]
) -> Iterator[str]:
    lm = dspy.LM(**build_stream_lm_kwargs(config))
    module = FeatureChatModule(feature=feature)
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


@transaction.atomic
def create_feature_chat_exchange(
    *,
    thread: FeatureChatThread,
    config: ProjectLLMConfig,
    user_text: str,
    assistant_text: str,
) -> tuple[FeatureChatMessage, FeatureChatMessage]:
    user_message = FeatureChatMessage.create_message(
        thread=thread,
        role=FeatureChatMessage.Role.USER,
        text=user_text.strip(),
    )
    assistant_message = thread.create_feature_chat_assistant_message(
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
    config = thread.feature.project.get_project_llm_config()
    lm = dspy.LM(**build_lm_kwargs(config))
    module = FeatureChatModule(feature=thread.feature)
    with dspy.context(lm=lm):
        prediction = module(
            project_name=thread.feature.project.name,
            project_description=thread.feature.project.description,
            feature_name=thread.feature.name,
            feature_description=thread.feature.description,
            project_context=build_feature_chat_project_context(
                feature=thread.feature,
                user_message=cleaned_text,
            ),
            conversation_history=build_conversation_history(thread),
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
