import asyncio
import contextvars
import json
import re
import threading
from dataclasses import dataclass
from queue import Queue
from time import perf_counter
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
from projects.project_memory import (
    get_project_memory_store,
)


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
        conversation_history: dspy.History,
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
            queryset = Feature.get_features_for_project_with_relations(
                self.feature.project_id
            ).exclude(id=self.feature.id)
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
            queryset = Task.get_base_queryset_with_relations().filter(
                feature__project_id=self.feature.project_id
            )
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
            for feature in Feature.get_features_for_project_with_relations(
                self.feature.project_id
            )
            .filter(id__in=feature_ids)
            .exclude(id=self.feature.id)
        }
        return [
            features_by_id[feature_id]
            for feature_id in feature_ids
            if feature_id in features_by_id
        ]

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


AgentActivityStreamEvent = dict[str, Any]


class AgentActivityStreamStatusProvider(dspy.streaming.StatusMessageProvider):
    def __init__(self) -> None:
        self._tool_started_at: list[float] = []
        self._lm_started_at: list[float] = []
        self._tool_step = 0
        self._lm_step = 0

    def tool_start_status_message(self, instance: Any, inputs: dict[str, Any]) -> str | None:
        tool_name = getattr(instance, "name", "")
        if tool_name not in {"search_other_features", "search_project_tasks"}:
            return None

        self._tool_step += 1
        self._tool_started_at.append(perf_counter())
        return json.dumps(
            {
                "type": "activity",
                "status": "running",
                "tool": tool_name,
                "label": _build_tool_running_label(tool_name),
                "detail": _summarize_tool_inputs(inputs),
                "step": self._tool_step,
            }
        )

    def tool_end_status_message(self, outputs: Any) -> str:
        output_text = str(outputs)
        tool_name = _infer_tool_name_from_output(output_text)
        elapsed_ms = self._pop_elapsed_ms(self._tool_started_at)
        return json.dumps(
            {
                "type": "activity",
                "status": "complete",
                "tool": tool_name,
                "label": _build_tool_complete_label(tool_name, output_text),
                "detail": _append_elapsed_detail(_summarize_tool_output(output_text), elapsed_ms),
                "step": self._tool_step,
                "elapsed_ms": elapsed_ms,
            }
        )

    def lm_start_status_message(self, instance: Any, inputs: dict[str, Any]) -> str:
        del inputs
        self._lm_step += 1
        self._lm_started_at.append(perf_counter())
        model_name = _truncate_status_value(getattr(instance, "model", "configured model"), max_length=100)
        return json.dumps(
            {
                "type": "activity",
                "status": "running",
                "tool": "language_model",
                "label": "Calling language model",
                "detail": f"model: {model_name}",
                "step": self._lm_step,
            }
        )

    def lm_end_status_message(self, outputs: Any) -> str:
        del outputs
        elapsed_ms = self._pop_elapsed_ms(self._lm_started_at)
        return json.dumps(
            {
                "type": "activity",
                "status": "complete",
                "tool": "language_model",
                "label": "Language model finished",
                "detail": f"elapsed: {_format_elapsed_ms(elapsed_ms)}",
                "step": self._lm_step,
                "elapsed_ms": elapsed_ms,
            }
        )

    def _pop_elapsed_ms(self, started_at_values: list[float]) -> int | None:
        if not started_at_values:
            return None
        started_at = started_at_values.pop()
        return max(0, round((perf_counter() - started_at) * 1000))


def _build_tool_running_label(tool_name: str) -> str:
    labels = {
        "search_other_features": "Searching related features",
        "search_project_tasks": "Searching project tasks",
    }
    return labels.get(tool_name, "Using project context")


def _build_tool_complete_label(tool_name: str, output_text: str) -> str:
    if tool_name == "search_other_features":
        count = _count_result_lines(output_text, prefix="- Feature ")
        if count == 1:
            return "Found 1 related feature"
        return f"Found {count} related features"
    if tool_name == "search_project_tasks":
        count = _count_result_lines(output_text, prefix="- Task ")
        if count == 1:
            return "Found 1 matching task"
        return f"Found {count} matching tasks"
    return "Project context search complete"


def _summarize_tool_inputs(inputs: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ["query", "feature_name", "status", "assignee", "limit"]:
        value = inputs.get(key)
        if value is None or value == "":
            continue
        parts.append(f"{key}: {_truncate_status_value(value)}")
    if not parts:
        return "Using current project context."
    return ", ".join(parts)


def _summarize_tool_output(output_text: str) -> str:
    first_line = output_text.strip().splitlines()[0] if output_text.strip() else ""
    if not first_line:
        return "No details returned."
    return _truncate_status_value(first_line, max_length=120)


def _append_elapsed_detail(detail: str, elapsed_ms: int | None) -> str:
    if elapsed_ms is None:
        return detail
    return f"{detail} elapsed: {_format_elapsed_ms(elapsed_ms)}"


def _format_elapsed_ms(elapsed_ms: int | None) -> str:
    if elapsed_ms is None:
        return "unknown"
    if elapsed_ms < 1000:
        return f"{elapsed_ms} ms"
    return f"{elapsed_ms / 1000:.1f} s"


def _truncate_status_value(value: Any, *, max_length: int = 80) -> str:
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1]}..."


def _infer_tool_name_from_output(output_text: str) -> str:
    if output_text.startswith("Other project features:") or "other features matched" in output_text:
        return "search_other_features"
    if output_text.startswith("Project tasks:") or "project tasks matched" in output_text:
        return "search_project_tasks"
    return "project_context"


def _count_result_lines(output_text: str, *, prefix: str) -> int:
    return sum(1 for line in output_text.splitlines() if line.startswith(prefix))


def _parse_status_message_event(message: str) -> AgentActivityStreamEvent | None:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "activity":
        return None
    return payload


def _sync_iter_async_stream(async_generator: Any) -> Iterator[Any]:
    queue: Queue[Any] = Queue()
    stop_sentinel = object()
    context = contextvars.copy_context()

    def producer() -> None:
        async def runner() -> None:
            try:
                async for item in async_generator:
                    queue.put(item)
            except BaseException as exc:
                queue.put(exc)
            finally:
                queue.put(stop_sentinel)

        context.run(asyncio.run, runner())

    thread = threading.Thread(target=producer, daemon=True)
    thread.start()

    while True:
        item = queue.get()
        if item is stop_sentinel:
            break
        if isinstance(item, BaseException):
            raise item
        yield item


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
    conversation_history: dspy.History,
    user_message: str,
) -> dict[str, Any]:
    return {
        "project_name": thread.feature.project.name,
        "project_description": thread.feature.project.description,
        "feature_name": thread.feature.name,
        "feature_description": thread.feature.description,
        "conversation_history": conversation_history,
        "user_message": user_message,
    }


def prepare_feature_chat_request(
    *,
    thread: FeatureChatThread,
    text: str,
    user: object,
) -> tuple[str, ProjectLLMConfig, dict[str, Any]]:
    del user
    cleaned_text = text.strip()
    if not cleaned_text:
        raise FeatureChatConfigurationError("Message text is required.")

    config = thread.feature.project.get_project_llm_config()
    module_inputs = build_feature_chat_module_inputs(
        thread=thread,
        conversation_history=build_conversation_history(thread),
        user_message=cleaned_text,
    )
    return cleaned_text, config, module_inputs


def iter_feature_chat_response_text(
    *, feature: Feature, config: ProjectLLMConfig, module_inputs: dict[str, Any]
) -> Iterator[str]:
    for event in iter_agent_activity_stream_response_events(
        feature=feature,
        config=config,
        module_inputs=module_inputs,
    ):
        if event["type"] == "chunk":
            yield str(event["text"])


def iter_agent_activity_stream_response_events(
    *, feature: Feature, config: ProjectLLMConfig, module_inputs: dict[str, Any]
) -> Iterator[AgentActivityStreamEvent]:
    yield {
        "type": "activity",
        "status": "running",
        "tool": "feature_chat",
        "label": "Reviewing feature context",
        "detail": "Preparing the agent request.",
    }
    lm = dspy.LM(**build_stream_lm_kwargs(config))
    module = FeatureChatModule(feature=feature)
    stream_module = dspy.streamify(
        module,
        status_message_provider=AgentActivityStreamStatusProvider(),
        stream_listeners=[
            dspy.streaming.StreamListener(signature_field_name="assistant_reply"),
        ],
    )
    final_prediction: dspy.Prediction | None = None
    yielded_chunk = False

    with dspy.context(lm=lm):
        for value in _sync_iter_async_stream(stream_module(**module_inputs)):
            if isinstance(value, dspy.streaming.StreamResponse):
                if value.chunk:
                    yielded_chunk = True
                    yield {"type": "chunk", "text": value.chunk}
                continue
            if isinstance(value, dspy.streaming.StatusMessage):
                event = _parse_status_message_event(value.message)
                if event is not None:
                    yield event
                continue
            if isinstance(value, dspy.Prediction):
                final_prediction = value

    if final_prediction is None:
        raise RuntimeError("Feature chat stream completed without a final prediction.")
    if not yielded_chunk and final_prediction.assistant_reply:
        yield {"type": "chunk", "text": final_prediction.assistant_reply}


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
