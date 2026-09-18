"""`POST /api/v1/chat`: the AI SDK UI message stream (system design §6).

The body is what `useChat`'s `DefaultChatTransport` sends. A body that is not
a conversation is a 422 problem+json before any stream starts; everything
after that (no key, spend limit, model errors) arrives as stream parts.
GZip must never wrap this route: Starlette's GZipMiddleware skips
`text/event-stream`, and no other compression is installed.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from stockticker.ai.context import build_chat_deps
from stockticker.ai.convert import ChatRequest
from stockticker.ai.loop import new_message_id, stream_answer
from stockticker.ai.stream import SSE_MEDIA_TYPE, UI_MESSAGE_STREAM_HEADERS, until_disconnected
from stockticker.api.problems import Problem
from stockticker.config import Settings, get_settings
from stockticker.models.problem import ProblemDetail
from stockticker.models.views import ViewSpec

router = APIRouter(tags=["chat"])


class DataViewPart(BaseModel):
    """The `data-view` stream part: a table or chart built from a result the
    model has seen. Documented here so the web app can generate its type."""

    type: Literal["data-view"] = "data-view"
    id: str
    data: ViewSpec


_STREAM_DESCRIPTION = (
    "An AI SDK UI message stream (v1): `data: <json>` server-sent events, ending with `data: [DONE]`. "
    "The schema shown is the app-specific `data-view` part; the other parts are the AI SDK's own."
)


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": _STREAM_DESCRIPTION,
            "model": DataViewPart,
        },
        415: {"model": ProblemDetail},
        422: {"model": ProblemDetail},
    },
    openapi_extra={
        "responses": {
            "200": {"content": {SSE_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/DataViewPart"}}}}
        }
    },
)
async def chat(
    request: Request, body: ChatRequest, settings: Settings = Depends(get_settings)
) -> StreamingResponse:
    if not any(message.role == "user" for message in body.messages):
        raise Problem("invalid-chat-request", 422, "The conversation has no user message.")
    deps = build_chat_deps(settings)
    source = stream_answer(deps, body.messages, new_message_id())
    events: Any = until_disconnected(source, request.is_disconnected)
    return StreamingResponse(events, media_type=SSE_MEDIA_TYPE, headers=UI_MESSAGE_STREAM_HEADERS)
