"""No database needed: these routes (404/405/422/415, and every stub
router) fail before any handler touches the DB."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from stockticker.api.app import app
from stockticker.api.middleware import RequestIDMiddleware
from stockticker.api.problems import Problem, problem_type_uri, register_problem_handlers, slug_for

client = TestClient(app, base_url="http://127.0.0.1")


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


def test_422_is_problem_json_with_field_errors() -> None:
    response = client.post("/api/v1/notes", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["status"] == 422
    assert body["errors"]
    assert any(e["loc"] == ["body", "start_date"] for e in body["errors"])


def test_write_without_json_content_type_is_415() -> None:
    response = client.post("/api/v1/notes", content=b"{}", headers={"content-type": "text/plain"})
    assert response.status_code == 415
    assert response.headers["content-type"] == "application/problem+json"


def test_every_response_carries_request_id() -> None:
    response = client.get("/nope")
    assert response.headers.get("x-request-id")


def test_415_response_still_carries_request_id() -> None:
    response = client.post("/api/v1/notes", content=b"{}", headers={"content-type": "text/plain"})
    assert response.headers.get("x-request-id")


def test_stub_router_returns_501_problem_json() -> None:
    response = client.get("/api/v1/market")
    assert response.status_code == 501
    assert response.headers["content-type"] == "application/problem+json"


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
        allow_origins=["http://127.0.0.1:3000"],
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


def test_500_keeps_request_id_and_cors_headers() -> None:
    standalone_client = TestClient(
        _standalone_app(), base_url="http://127.0.0.1", raise_server_exceptions=False
    )
    response = standalone_client.get("/boom", headers={"origin": "http://127.0.0.1:3000"})
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers.get("x-request-id")
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"


def test_domain_problem_exception_uses_its_own_slug() -> None:
    standalone_client = TestClient(
        _standalone_app(), base_url="http://127.0.0.1", raise_server_exceptions=False
    )
    response = standalone_client.get("/domain-error")
    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "https://stockticker.local/problems/unknown-cik"
    assert body["detail"] == "no company with that CIK"
