"""`ProblemJSONTrustedHostMiddleware` (issue #32, round 2): a rejected
`Host` header must come back `application/problem+json`, not
`TrustedHostMiddleware`'s own `PlainTextResponse`. An allowed host's own
400 must keep its body."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from stockticker.api.app import app
from stockticker.api.middleware import ProblemJSONTrustedHostMiddleware

client = TestClient(app, base_url="http://127.0.0.1")


def test_unknown_host_header_is_rejected_as_problem_json() -> None:
    response = client.get("/api/v1/health/live", headers={"host": "evil.example.com"})
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 400
    assert body["type"] == "https://stockticker.local/problems/invalid-host-header"


def test_unknown_host_header_still_carries_request_id() -> None:
    response = client.get("/api/v1/health/live", headers={"host": "evil.example.com"})
    assert response.headers.get("x-request-id")


def test_allowed_host_header_passes_through() -> None:
    response = client.get("/api/v1/health/live", headers={"host": "127.0.0.1"})
    assert response.status_code == 200


def test_allowed_host_deliberate_400_keeps_original_body() -> None:
    """Regression: capturing_send must not treat every downstream 400 as a
    TrustedHost rejection (thermo + correctness, #32 gate)."""
    probe = FastAPI()
    probe.add_middleware(ProblemJSONTrustedHostMiddleware, allowed_hosts=["127.0.0.1", "testserver"])

    @probe.get("/deliberate-400")
    def deliberate_400() -> PlainTextResponse:
        return PlainTextResponse("app said no", status_code=400)

    probe_client = TestClient(probe, base_url="http://127.0.0.1")
    response = probe_client.get("/deliberate-400", headers={"host": "127.0.0.1"})
    assert response.status_code == 400
    assert response.text == "app said no"
    assert "invalid-host-header" not in response.text
    assert response.headers["content-type"].startswith("text/plain")
