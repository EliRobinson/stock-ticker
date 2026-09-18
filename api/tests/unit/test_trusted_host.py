"""`ProblemJSONTrustedHostMiddleware` (issue #32, round 2): a rejected
`Host` header must come back `application/problem+json`, not
`TrustedHostMiddleware`'s own `PlainTextResponse`."""

from __future__ import annotations

from fastapi.testclient import TestClient

from stockticker.api.app import app

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
