"""`application/problem+json` (RFC 9457) for every error response, including
FastAPI's own 404, 405, and 422 (system design §5).

Each `type` is a stable URI, `https://stockticker.local/problems/<slug>` --
a kebab-case slug of the HTTP reason phrase for the generic handlers
(`404` -> `not-found`), or a domain-specific slug for a raised `Problem`
(`Problem("unknown-cik", 422, "...")` -> `.../problems/unknown-cik`), so a
client can switch on `type` instead of the numeric status.

A response built by `problem_response` carries `X-Request-ID` and the CORS
allow-origin header itself, rather than relying on `RequestIDMiddleware`/
`CORSMiddleware` to add them: an exception handler registered for the bare
`Exception` type (i.e. `unhandled_exception_handler`, for a genuine 500) is
invoked by Starlette's `ServerErrorMiddleware`, which sits *outside* every
`add_middleware` layer -- a response built there never passes back through
our own middleware, so it would otherwise ship with neither header."""

from __future__ import annotations

import re
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from stockticker.config import get_settings
from stockticker.logging import get_logger
from stockticker.models.problem import ProblemDetail

logger = get_logger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_TYPE_BASE = "https://stockticker.local/problems"

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class Problem(Exception):
    """Raise `Problem(slug, status, detail)` from a route for a
    domain-specific error (`Problem("unknown-cik", 422, "no company with
    that CIK")`), instead of `HTTPException` with a made-up detail string
    -- the slug becomes a stable, documented `type` URI."""

    def __init__(self, slug: str, status: int, detail: str | None = None) -> None:
        self.slug = slug
        self.status = status
        self.detail = detail
        super().__init__(detail or slug)


def _title_for(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


def slug_for(status_code: int) -> str:
    """`_title_for(415)` -> "Unsupported Media Type" -> "unsupported-media-type"."""
    return _SLUG_NON_ALNUM.sub("-", _title_for(status_code).lower()).strip("-")


def problem_type_uri(slug: str) -> str:
    return f"{PROBLEM_TYPE_BASE}/{slug}"


def _extra_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    request_id = request.scope.get("state", {}).get("request_id")
    if request_id:
        headers["X-Request-ID"] = request_id
    origin = request.headers.get("origin")
    web_origin = get_settings().web_origin
    if origin and origin == web_origin:
        headers["Access-Control-Allow-Origin"] = web_origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return headers


def problem_response(
    request: Request,
    *,
    status_code: int,
    detail: str | None,
    slug: str | None = None,
    errors: list[dict[str, object]] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        type=problem_type_uri(slug or slug_for(status_code)),
        title=_title_for(status_code),
        status=status_code,
        detail=detail,
        instance=str(request.url.path),
        errors=errors,
    )
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=status_code,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=_extra_headers(request),
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # FastAPI's own HTTPException subclasses Starlette's, so registering
    # this handler for StarletteHTTPException alone covers both; the
    # broader `Exception` parameter type is what add_exception_handler's
    # signature requires.
    assert isinstance(exc, StarletteHTTPException)
    return problem_response(request, status_code=exc.status_code, detail=str(exc.detail))


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return problem_response(
        request,
        status_code=422,
        detail="Request validation failed.",
        errors=jsonable_encoder(exc.errors()),
    )


async def problem_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, Problem)
    return problem_response(request, status_code=exc.status, detail=exc.detail, slug=exc.slug)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request.scope.get("state", {}).get("request_id")
    logger.error(
        "api.unhandled_exception", path=request.url.path, error=str(exc), request_id=request_id, exc_info=exc
    )
    return problem_response(request, status_code=500, detail="An unexpected error occurred.")


def register_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Problem, problem_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
