"""FastAPI app factory. `create_app()` is the single entry point; `app` (the
module-level instance) is what `uvicorn stockticker.api.app:app` imports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from stockticker.api.middleware import (
    ProblemJSONTrustedHostMiddleware,
    RequestIDMiddleware,
    enforce_json_content_type,
)
from stockticker.api.problems import register_problem_handlers
from stockticker.api.routers import chat, companies, events, health, listings, market, notes, status
from stockticker.config import get_settings
from stockticker.db import dispose_engines
from stockticker.logging import configure_logging

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engines()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(json=settings.environment != "development")

    app = FastAPI(title="Stock Ticker API", version="0.1.0", lifespan=lifespan)

    register_problem_handlers(app)

    app.add_middleware(ProblemJSONTrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Middleware order: the *last* `add_middleware`/`middleware("http")` call
    # becomes the outermost layer (Starlette builds the stack in reverse
    # insertion order), so RequestIDMiddleware is added last to guarantee
    # every response — including one short-circuited by the JSON
    # content-type check — carries `X-Request-ID`.
    app.middleware("http")(enforce_json_content_type)
    app.add_middleware(RequestIDMiddleware)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(status.router, prefix=API_PREFIX)
    app.include_router(market.router, prefix=API_PREFIX)
    app.include_router(companies.router, prefix=API_PREFIX)
    app.include_router(listings.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)
    app.include_router(notes.router, prefix=API_PREFIX)
    app.include_router(chat.router, prefix=API_PREFIX)

    return app


app = create_app()
