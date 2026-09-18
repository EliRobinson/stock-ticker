"""Request-scoped middleware: request IDs, JSON content-type enforcement on
writes, and a `TrustedHostMiddleware` wrapper that speaks problem+json
(system design §5)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence

import structlog
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from stockticker.api.problems import cors_headers, problem_response

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
    (non-exception) path; `stockticker.api.problems.problem_response` adds
    it again for every problem+json response, since a 500's response is
    built outside this middleware and never passes back through
    `send_wrapper`.
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
        if content_type.split(";")[0].strip().lower() != "application/json":
            # Registered via `app.middleware("http")` after `CORSMiddleware`
            # (app.py), which puts it *outside* CORSMiddleware in the stack
            # -- this short-circuit never calls `call_next`, so the response
            # never passes back through CORSMiddleware and needs its CORS
            # headers added directly, the same reasoning as
            # `unhandled_exception_handler` (see problems.py).
            return problem_response(
                request,
                status_code=415,
                detail="Writes must send 'Content-Type: application/json'.",
                extra_headers=cors_headers(request),
            )
    return await call_next(request)


class ProblemJSONTrustedHostMiddleware:
    """Wraps Starlette's `TrustedHostMiddleware` so a rejected host is
    reported as `application/problem+json`, like every other error in this
    API, instead of `TrustedHostMiddleware`'s own `PlainTextResponse`.

    Delegates the actual host matching to the real `TrustedHostMiddleware`
    (wildcard patterns, the `www.` redirect) and only intercepts the one
    response shape it can produce for a rejection: a plain-text 400. This
    middleware sits where `TrustedHostMiddleware` used to -- *inside*
    `CORSMiddleware` (`app.py` adds `TrustedHostMiddleware` before
    `CORSMiddleware`) -- so a rejection still passes back through
    `CORSMiddleware` normally and needs no CORS headers added here."""

    def __init__(self, app: ASGIApp, *, allowed_hosts: Sequence[str]) -> None:
        self.app = app
        self._inner = TrustedHostMiddleware(app, allowed_hosts=list(allowed_hosts))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._inner(scope, receive, send)
            return

        rejected = False

        async def capturing_send(message: Message) -> None:
            nonlocal rejected
            if message["type"] == "http.response.start":
                rejected = message["status"] == 400
                if rejected:
                    return
            elif rejected:
                return
            await send(message)

        await self._inner(scope, receive, capturing_send)

        if rejected:
            request = Request(scope, receive=receive)
            response = problem_response(
                request,
                status_code=400,
                detail="Invalid host header.",
                slug="invalid-host-header",
            )
            await response(scope, receive, send)
