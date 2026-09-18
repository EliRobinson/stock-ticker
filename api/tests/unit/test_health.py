"""`/api/v1/health/ready` (reliability review): must report 503, not 500,
when the database is unreachable -- the connection is acquired inside the
route's own try, not via a FastAPI `Depends()` generator dependency (a
failing dependency raises during FastAPI's own dependency-resolution
phase, before the route body's try/except ever runs). No real database
needed: the engine is monkeypatched to point at a port nothing listens on,
so the connection fails immediately."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

import stockticker.api.routers.health as health_module
from stockticker.api.app import app

client = TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def unreachable_app_writer_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    engine = create_async_engine("postgresql+asyncpg://nobody:nobody@127.0.0.1:1/nonexistent")
    monkeypatch.setattr(health_module, "get_api_app_writer_engine", lambda: engine)
    yield


def test_health_ready_is_503_not_500_when_the_database_is_unreachable(
    unreachable_app_writer_engine: None,
) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "database unreachable"
