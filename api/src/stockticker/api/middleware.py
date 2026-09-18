"""Request-scoped middleware: request IDs and JSON content-type enforcement
on writes (system design §5)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})


class RequestIDMiddleware:
    """Assigns `request.state.request_id` and binds it into structlog's
    contextvars *before any log line can run* -- both survive even for a
    request that ends in an unhandled exception, since `contextvars` is
    scoped to this request's own asyncio task and needs no explicit
    unbind. (An earlier version unbound in a `finally`, which ran *before*
    `unhandled_exception_handler` -- that handler is invoked by Starlette's
    `ServerErrorMiddleware`, outside this middleware entirely, so the
    `finally` had already stripped `request_id` from the context by the
    time the 500 was logged.)

    `X-Request-ID` on the response is still added here for the normal
    (non-exception) path; `stockticker.api.problems._respond` adds it again
    for every problem+json response, since a 500's response is built
    outside this middleware and never passes back through `send_wrapper`.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
            await send(message)

        await self.app(scope, receive, send_wrapper)


async def enforce_json_content_type(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.method in WRITE_METHODS:
        content_type = request.headers.get("content-type", "")
        if content_type.split(";")[0].strip() != "application/json":
            from stockticker.api.problems import _respond

            return _respond(
                request,
                status_code=415,
                detail="Writes must send 'Content-Type: application/json'.",
            )
    return await call_next(request)
