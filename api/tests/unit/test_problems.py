"""No database needed: these routes (404/405/422/415, and every stub
router) fail before any handler touches the DB.

`PUT /api/v1/notes/{id}` is a real route now (it isn't a stub), so its
`conn: AsyncConnection = Depends(get_app_writer_connection)` *is* resolved
even for a request whose body fails validation -- FastAPI solves every
dependency together with body parsing, not body-first. `dependency_overrides`
swaps in a connection-shaped stub that never touches a socket, so the 422
tests below still need no database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from stockticker.api.app import app
from stockticker.api.middleware import RequestIDMiddleware
from stockticker.api.problems import Problem, problem_type_uri, register_problem_handlers, slug_for
from stockticker.db import get_app_writer_connection

client = TestClient(app, base_url="http://127.0.0.1")
_NOTE_URL = f"/api/v1/notes/{uuid.uuid4()}"
ORIGIN = "http://127.0.0.1:3000"


async def _fake_connection() -> AsyncIterator[Any]:
    yield None


@pytest.fixture
def db_free() -> Iterator[None]:
    """Overrides `get_app_writer_connection` for the app's own `client` for
    the duration of one test, then restores it -- `app` is a shared module
    object, so a leaked override would silently give other test modules
    (the real-DB integration tests especially) a fake connection instead of
    a real one."""
    app.dependency_overrides[get_app_writer_connection] = _fake_connection
    try:
        yield
    finally:
        del app.dependency_overrides[get_app_writer_connection]


def test_slug_for_kebab_cases_the_reason_phrase() -> None:
    assert slug_for(404) == "not-found"
    assert slug_for(405) == "method-not-allowed"
    assert slug_for(422) == "unprocessable-entity"
    assert slug_for(415) == "unsupported-media-type"


def test_problem_type_uri_is_stable() -> None:
    assert problem_type_uri("not-found") == "https://stockticker.local/problems/not-found"


def test_404_is_problem_json() -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 404
    assert body["type"] == "https://stockticker.local/problems/not-found"
    assert body["instance"] == "/nope"


def test_405_is_problem_json() -> None:
    response = client.delete("/api/v1/market")
    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"


def test_422_is_problem_json_with_field_errors(db_free: None) -> None:
    response = client.put(_NOTE_URL, json={})
    assert response.status_code == 422
    body = response.json()
    assert body["status"] == 422
    assert body["errors"]
    assert any(e["loc"] == ["body", "start_date"] for e in body["errors"])


def test_write_without_json_content_type_is_415() -> None:
    response = client.put(_NOTE_URL, content=b"{}", headers={"content-type": "text/plain"})
    assert response.status_code == 415
    assert response.headers["content-type"] == "application/problem+json"


def test_every_response_carries_request_id() -> None:
    response = client.get("/nope")
    assert response.headers.get("x-request-id")


def test_415_response_still_carries_request_id() -> None:
    response = client.put(_NOTE_URL, content=b"{}", headers={"content-type": "text/plain"})
    assert response.headers.get("x-request-id")


def test_health_live_needs_no_database() -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _standalone_app() -> FastAPI:
    """A minimal app -- same middleware/handler wiring as the real one --
    with two routes designed to fail, so the 500 and Problem paths can be
    exercised without touching production routes."""
    standalone = FastAPI()
    register_problem_handlers(standalone)
    standalone.add_middleware(
        CORSMiddleware,
        allow_origins=[ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    standalone.add_middleware(RequestIDMiddleware)

    @standalone.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    @standalone.get("/domain-error")
    async def domain_error() -> None:
        raise Problem("unknown-cik", 422, "no company with that CIK")

    return standalone


@pytest.fixture
def standalone_client() -> Iterator[TestClient]:
    with TestClient(_standalone_app(), base_url="http://127.0.0.1", raise_server_exceptions=False) as c:
        yield c


def _assert_exactly_one_cors_header_pair(response: Any) -> None:
    """A duplicated `Access-Control-Allow-Origin` breaks CORS in some
    browsers (round 2 FIX-LATER, issue #32) -- `.headers.get(...)` would
    hide a duplicate by only returning one value, so this reads the raw,
    possibly-repeated header list instead."""
    assert response.headers.get_list("access-control-allow-origin") == [ORIGIN]
    assert response.headers.get_list("vary") == ["Origin"]


def test_500_keeps_request_id_and_cors_headers(standalone_client: TestClient) -> None:
    response = standalone_client.get("/boom", headers={"origin": ORIGIN})
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers.get("x-request-id")
    assert response.headers.get("access-control-allow-origin") == ORIGIN


def test_domain_problem_exception_uses_its_own_slug(standalone_client: TestClient) -> None:
    response = standalone_client.get("/domain-error")
    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "https://stockticker.local/problems/unknown-cik"
    assert body["detail"] == "no company with that CIK"


@pytest.mark.parametrize(
    "case",
    [
        {"path": "/nope", "status": 404},
        {"path": "/domain-error", "status": 422},
        {"path": "/boom", "status": 500},
    ],
    ids=["404", "domain-problem", "500"],
)
def test_standalone_carries_exactly_one_cors_header_pair(
    standalone_client: TestClient, case: dict[str, object]
) -> None:
    response = standalone_client.get(str(case["path"]), headers={"origin": ORIGIN})
    assert response.status_code == case["status"]
    _assert_exactly_one_cors_header_pair(response)


def test_422_carries_exactly_one_cors_header_pair(db_free: None) -> None:
    response = client.put(_NOTE_URL, json={}, headers={"origin": ORIGIN})
    assert response.status_code == 422
    _assert_exactly_one_cors_header_pair(response)


def test_415_carries_exactly_one_cors_header_pair() -> None:
    # enforce_json_content_type sits outside CORSMiddleware too (see
    # middleware.py) -- same failure mode as the bare-Exception handler if
    # its CORS headers were ever dropped or duplicated.
    response = client.put(
        _NOTE_URL,
        content=b"{}",
        headers={"content-type": "text/plain", "origin": ORIGIN},
    )
    assert response.status_code == 415
    _assert_exactly_one_cors_header_pair(response)
