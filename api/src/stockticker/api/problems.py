"""`application/problem+json` (RFC 9457) for every error response, including
FastAPI's own 404, 405, and 422 (system design §5).

Each `type` is a stable URI, `https://stock-ticker.local/problems/<slug>` --
a kebab-case slug of the HTTP reason phrase (`404` -> `not-found`), so a
client can switch on `type` instead of the numeric status."""

from __future__ import annotations

import re
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from stockticker.logging import get_logger
from stockticker.models.problem import ProblemDetail

logger = get_logger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_TYPE_BASE = "https://stock-ticker.local/problems"

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _title_for(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


def slug_for(status_code: int) -> str:
    """`_title_for(415)` -> "Unsupported Media Type" -> "unsupported-media-type"."""
    return _SLUG_NON_ALNUM.sub("-", _title_for(status_code).lower()).strip("-")


def problem_type_uri(status_code: int) -> str:
    return f"{PROBLEM_TYPE_BASE}/{slug_for(status_code)}"


def _respond(
    request: Request,
    *,
    status_code: int,
    detail: str | None,
    errors: list[dict[str, object]] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        type=problem_type_uri(status_code),
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
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # FastAPI's own HTTPException subclasses Starlette's, so registering
    # this handler for StarletteHTTPException alone covers both; the
    # broader `Exception` parameter type is what add_exception_handler's
    # signature requires.
    assert isinstance(exc, StarletteHTTPException)
    return _respond(request, status_code=exc.status_code, detail=str(exc.detail))


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _respond(
        request,
        status_code=422,
        detail="Request validation failed.",
        errors=jsonable_encoder(exc.errors()),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("api.unhandled_exception", path=request.url.path, error=str(exc), exc_info=exc)
    return _respond(request, status_code=500, detail="An unexpected error occurred.")


def register_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
