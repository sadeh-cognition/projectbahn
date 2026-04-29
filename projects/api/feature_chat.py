from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, StreamingHttpResponse
from ninja.errors import HttpError

from projects.api import api
from projects.api.common import (
    User,
    require_authenticated_user,
)
from projects.feature_chat import (
    FeatureChatConfigurationError,
    create_feature_chat_exchange,
    create_feature_chat_thread,
    iter_agent_activity_stream_response_events,
    prepare_feature_chat_request,
    serialize_message,
    serialize_thread,
)
from projects.models import Feature, FeatureChatThread
from projects.project_memory import ProjectMemoryError
from projects.schemas import (
    FeatureChatMessageResponseSchema,
    FeatureChatStreamRequestSchema,
    FeatureChatThreadCreateSchema,
    FeatureChatThreadDetailSchema,
    FeatureChatThreadResponseSchema,
)


def get_owned_feature_chat_thread(
    *, feature_id: int, thread_id: int, user: User
) -> FeatureChatThread:
    return FeatureChatThread.get_by_id_and_owner_or_404(
        thread_id=thread_id,
        feature_id=feature_id,
        owner_id=user.id,
    )


@api.get(
    "/features/{feature_id}/chat-threads",
    response=list[FeatureChatThreadResponseSchema],
)
def list_feature_chat_threads(
    request: HttpRequest, feature_id: int
) -> list[FeatureChatThreadResponseSchema]:
    user = require_authenticated_user(request)
    Feature.get_by_id_or_404(feature_id)
    threads = FeatureChatThread.get_threads_for_feature_and_owner(
        feature_id=feature_id, owner_id=user.id
    )
    return [
        FeatureChatThreadResponseSchema.model_validate(serialize_thread(thread))
        for thread in threads
    ]


@api.post(
    "/features/{feature_id}/chat-threads", response=FeatureChatThreadResponseSchema
)
def create_feature_thread(
    request: HttpRequest,
    feature_id: int,
    payload: FeatureChatThreadCreateSchema,
) -> FeatureChatThreadResponseSchema:
    user = require_authenticated_user(request)
    feature = Feature.get_by_id_with_project_or_404(feature_id)
    try:
        thread = create_feature_chat_thread(
            feature=feature, user=user, title=payload.title
        )
    except FeatureChatConfigurationError as exc:
        raise HttpError(400, str(exc)) from exc
    return FeatureChatThreadResponseSchema.model_validate(serialize_thread(thread))


@api.get(
    "/features/{feature_id}/chat-threads/{thread_id}",
    response=FeatureChatThreadDetailSchema,
)
def get_feature_chat_thread(
    request: HttpRequest, feature_id: int, thread_id: int
) -> FeatureChatThreadDetailSchema:
    user = require_authenticated_user(request)
    thread = get_owned_feature_chat_thread(
        feature_id=feature_id, thread_id=thread_id, user=user
    )
    return FeatureChatThreadDetailSchema(
        thread=FeatureChatThreadResponseSchema.model_validate(serialize_thread(thread)),
        messages=[
            serialize_message(message)
            for message in thread.messages.order_by("date_created", "id")
        ],
    )


@api.post("/features/{feature_id}/chat-threads/{thread_id}/messages/stream")
def stream_feature_chat_message(
    request: HttpRequest,
    feature_id: int,
    thread_id: int,
    payload: FeatureChatStreamRequestSchema,
) -> StreamingHttpResponse:
    user = require_authenticated_user(request)
    try:
        thread = get_owned_feature_chat_thread(
            feature_id=feature_id,
            thread_id=thread_id,
            user=user,
        )
        user_text, config, module_inputs = prepare_feature_chat_request(
            thread=thread,
            text=payload.text,
            user=user,
        )
    except ProjectMemoryError as exc:
        raise HttpError(503, str(exc)) from exc
    except FeatureChatConfigurationError as exc:
        raise HttpError(400, str(exc)) from exc

    def event_stream() -> Any:
        assistant_chunks: list[str] = []
        try:
            for event in iter_agent_activity_stream_response_events(
                feature=thread.feature,
                config=config,
                module_inputs=module_inputs,
            ):
                if event["type"] == "chunk":
                    assistant_chunks.append(str(event["text"]))
                yield json.dumps(event) + "\n"
        except Exception as exc:
            yield (
                json.dumps(
                    {"type": "error", "detail": str(exc) or "Feature chat failed."}
                )
                + "\n"
            )
            return

        _user_message, assistant_message = create_feature_chat_exchange(
            thread=thread,
            config=config,
            user_text=user_text,
            assistant_text="".join(assistant_chunks),
        )
        assistant_payload = FeatureChatMessageResponseSchema.model_validate(
            serialize_message(assistant_message)
        ).model_dump(mode="json")
        thread_payload = FeatureChatThreadResponseSchema.model_validate(
            serialize_thread(thread)
        ).model_dump(mode="json")
        yield (
            json.dumps(
                {
                    "type": "done",
                    "assistant_message": assistant_payload,
                    "thread": thread_payload,
                    "llm_call_id": assistant_message.llm_call_id,
                }
            )
            + "\n"
        )

    response = StreamingHttpResponse(
        event_stream(), content_type="application/x-ndjson"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
