"""Request-scoped middleware: request IDs and JSON content-type enforcement
on writes (system design §5)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})


class RequestIDMiddleware:
    """Assigns `request.state.request_id`, binds it into structlog's
    contextvars for the duration of the request, and echoes it on every
    response via `X-Request-ID`."""

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

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")


async def enforce_json_content_type(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.method in WRITE_METHODS:
        content_type = request.headers.get("content-type", "")
        if content_type.split(";")[0].strip() != "application/json":
            from stockticker.api.problems import PROBLEM_MEDIA_TYPE, problem_type_uri
            from stockticker.models.problem import ProblemDetail

            problem = ProblemDetail(
                type=problem_type_uri(415),
                title="Unsupported Media Type",
                status=415,
                detail="Writes must send 'Content-Type: application/json'.",
                instance=str(request.url.path),
            )
            return JSONResponse(
                problem.model_dump(exclude_none=True),
                status_code=415,
                media_type=PROBLEM_MEDIA_TYPE,
            )
    return await call_next(request)
