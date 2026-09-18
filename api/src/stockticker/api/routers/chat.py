"""`POST /api/v1/chat`: the AI SDK UI message stream (system design §6).

The body is what `useChat`'s `DefaultChatTransport` sends. It is read with a
size cap (`MAX_BODY_BYTES`) before it is parsed, so a huge body is refused as a 413
without being held in memory. A body that is not a conversation is a 422
problem+json before any stream starts; everything after that (no key, spend
limit, model errors) arrives as stream parts. GZip must never wrap this
route: Starlette's GZipMiddleware skips `text/event-stream`, and no other
compression is installed.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from stockticker.ai.context import build_chat_deps
from stockticker.ai.convert import ChatRequest
from stockticker.ai.loop import answer_producer, new_message_id
from stockticker.ai.serialize import inline_schema_refs
from stockticker.ai.stream import SSE_MEDIA_TYPE, UI_MESSAGE_STREAM_HEADERS, until_disconnected
from stockticker.api.problems import Problem
from stockticker.config import Settings, get_settings
from stockticker.models.problem import ProblemDetail
from stockticker.models.views import ViewSpec

router = APIRouter(tags=["chat"])

MAX_BODY_BYTES = 1024 * 1024


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


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise _too_large()
    return bytes(body)


def _too_large() -> Problem:
    return Problem(
        "chat-request-too-large",
        413,
        f"The request is larger than {MAX_BODY_BYTES // (1024 * 1024)} MB. Start a new chat.",
    )


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={
        200: {"description": _STREAM_DESCRIPTION, "model": DataViewPart},
        413: {"model": ProblemDetail},
        415: {"model": ProblemDetail},
        422: {"model": ProblemDetail},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": inline_schema_refs(ChatRequest.model_json_schema())}},
        },
        "responses": {
            "200": {"content": {SSE_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/DataViewPart"}}}}
        },
    },
)
async def chat(request: Request, settings: Settings = Depends(get_settings)) -> StreamingResponse:
    try:
        body = ChatRequest.model_validate_json(await _read_body(request))
    except ValidationError as error:
        raise RequestValidationError(error.errors(include_url=False, include_context=False)) from None
    if not any(message.role == "user" for message in body.messages):
        raise Problem("invalid-chat-request", 422, "The conversation has no user message.")
    deps = build_chat_deps(settings)
    events: Any = until_disconnected(
        answer_producer(deps, body.messages, new_message_id()), request.is_disconnected
    )
    return StreamingResponse(events, media_type=SSE_MEDIA_TYPE, headers=UI_MESSAGE_STREAM_HEADERS)
