"""Contract tests for `/api/v1/notes` (system design §5, amended: `PUT
/notes/{id}` is an idempotent upsert with a client-supplied UUID, replacing
the old POST and PATCH; `GET /notes` is a range-overlap filter,
keyset-paginated)."""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest_asyncio
import seed
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.timeutil import today_ny

CIK = "9000000401"


def _encode_cursor(payload: dict[str, object]) -> str:
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest_asyncio.fixture
async def notes_company(app_writer_engine: AsyncEngine) -> AsyncIterator[None]:
    async with app_writer_engine.connect() as conn:
        await seed.insert_company(conn, cik=CIK, name="Zenith Test Notes Co")
        await seed.insert_listing(conn, symbol="ZTNT", cik=CIK)

    yield

    async with app_writer_engine.connect() as conn:
        await seed.cleanup_cik(conn, cik=CIK)


def _put(api_client: TestClient, note_id: uuid.UUID, **body: object) -> Any:
    return api_client.put(f"/api/v1/notes/{note_id}", json=body)


def test_put_creates_then_replaces(notes_company: None, api_client: TestClient) -> None:
    note_id = uuid.uuid4()
    try:
        created = _put(api_client, note_id, start_date="2024-01-01", body="  first draft  ")
        assert created.status_code == 201
        body = created.json()
        assert body["id"] == str(note_id)
        assert body["body"] == "first draft"
        assert body["end_date"] == "2024-01-01"  # defaults to start_date
        assert body["cik"] is None

        replaced = _put(api_client, note_id, start_date="2024-01-02", end_date="2024-01-05", body="revised")
        assert replaced.status_code == 200
        replaced_body = replaced.json()
        assert replaced_body["id"] == str(note_id)
        assert replaced_body["start_date"] == "2024-01-02"
        assert replaced_body["end_date"] == "2024-01-05"
        assert replaced_body["body"] == "revised"

        listed = api_client.get("/api/v1/notes", params={"market_only": True}).json()
        assert len([n for n in listed["items"] if n["id"] == str(note_id)]) == 1
    finally:
        api_client.delete(f"/api/v1/notes/{note_id}")


def test_put_identical_replace_is_a_no_op_and_keeps_updated_at(
    notes_company: None, api_client: TestClient
) -> None:
    note_id = uuid.uuid4()
    try:
        first = _put(api_client, note_id, start_date="2024-01-01", body="same")
        assert first.status_code == 201
        first_updated_at = first.json()["updated_at"]

        time.sleep(1.1)  # updated_at has second resolution; prove it truly didn't move
        second = _put(api_client, note_id, start_date="2024-01-01", body="same")
        assert second.status_code == 200
        assert second.json()["updated_at"] == first_updated_at
    finally:
        api_client.delete(f"/api/v1/notes/{note_id}")


def test_put_with_unknown_cik_is_422(api_client: TestClient) -> None:
    note_id = uuid.uuid4()
    response = _put(api_client, note_id, cik="0000000000", start_date="2024-01-01", body="x")
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/unknown-cik"


def test_put_rejects_date_past_horizon(api_client: TestClient) -> None:
    too_far = (today_ny() + timedelta(days=400)).isoformat()
    response = _put(api_client, uuid.uuid4(), start_date=too_far, body="x")
    assert response.status_code == 422


def test_put_rejects_nul_byte_in_body(api_client: TestClient) -> None:
    response = _put(api_client, uuid.uuid4(), start_date="2024-01-01", body="a\x00b")
    assert response.status_code == 422


def test_delete_is_idempotent(api_client: TestClient) -> None:
    note_id = uuid.uuid4()
    _put(api_client, note_id, start_date="2024-01-01", body="to delete")

    first = api_client.delete(f"/api/v1/notes/{note_id}")
    assert first.status_code == 204

    second = api_client.delete(f"/api/v1/notes/{note_id}")
    assert second.status_code == 204


def test_patch_no_longer_exists(api_client: TestClient) -> None:
    # Dropped: PUT covers the idempotent-upsert case PATCH used to serve.
    response = api_client.patch(f"/api/v1/notes/{uuid.uuid4()}", json={"body": "x"})
    assert response.status_code == 405


def test_get_notes_overlap_filter_and_ordering(notes_company: None, api_client: TestClient) -> None:
    ids = [uuid.uuid4() for _ in range(3)]
    try:
        _put(api_client, ids[0], cik=CIK, start_date="2024-01-01", end_date="2024-01-10", body="jan note")
        _put(api_client, ids[1], cik=CIK, start_date="2024-02-01", end_date="2024-02-05", body="feb note")
        _put(
            api_client,
            ids[2],
            cik=CIK,
            start_date="2023-12-20",
            end_date="2023-12-31",
            body="pre-window note",
        )

        response = api_client.get(
            "/api/v1/notes", params={"cik": CIK, "from": "2024-01-05", "to": "2024-01-31"}
        )
        assert response.status_code == 200
        body = response.json()
        returned_ids = [item["id"] for item in body["items"]]
        assert str(ids[0]) in returned_ids
        assert str(ids[1]) not in returned_ids
        assert str(ids[2]) not in returned_ids
    finally:
        for note_id in ids:
            api_client.delete(f"/api/v1/notes/{note_id}")


def test_get_notes_include_market_unions_whole_market_notes(
    notes_company: None, api_client: TestClient
) -> None:
    company_note = uuid.uuid4()
    market_note = uuid.uuid4()
    try:
        _put(api_client, company_note, cik=CIK, start_date="2024-01-01", body="company note")
        _put(api_client, market_note, start_date="2024-01-01", body="market-wide note")

        cik_only = api_client.get("/api/v1/notes", params={"cik": CIK}).json()
        assert {item["id"] for item in cik_only["items"]} == {str(company_note)}

        with_market = api_client.get("/api/v1/notes", params={"cik": CIK, "include_market": True}).json()
        returned = {item["id"] for item in with_market["items"]}
        assert str(company_note) in returned
        assert str(market_note) in returned
    finally:
        api_client.delete(f"/api/v1/notes/{company_note}")
        api_client.delete(f"/api/v1/notes/{market_note}")


def test_get_notes_cik_and_market_only_is_422(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/notes", params={"cik": CIK, "market_only": True})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/conflicting-filters"


def test_get_notes_from_after_to_is_422(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/notes", params={"from": "2024-06-01", "to": "2024-01-01"})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-range"


def test_get_notes_exact_limit_page_has_no_next_cursor(notes_company: None, api_client: TestClient) -> None:
    ids = [uuid.uuid4() for _ in range(3)]
    try:
        for i, note_id in enumerate(ids):
            _put(api_client, note_id, cik=CIK, start_date=f"2024-0{i + 1}-01", body=f"note {i}")

        response = api_client.get("/api/v1/notes", params={"cik": CIK, "limit": 3})
        body = response.json()
        assert len(body["items"]) == 3
        assert body["next_cursor"] is None
    finally:
        for note_id in ids:
            api_client.delete(f"/api/v1/notes/{note_id}")


def test_get_notes_invalid_cursor_is_422(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/notes", params={"cursor": "not-base64-json!!"})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-cursor"


def test_get_notes_cursor_with_null_id_is_422(api_client: TestClient) -> None:
    cursor = _encode_cursor({"start_date": "2024-01-01", "id": None})
    response = api_client.get("/api/v1/notes", params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-cursor"


def test_get_notes_cursor_with_list_id_is_422(api_client: TestClient) -> None:
    cursor = _encode_cursor({"start_date": "2024-01-01", "id": [1, 2]})
    response = api_client.get("/api/v1/notes", params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-cursor"


def test_get_notes_rejects_nul_byte_in_cik(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/notes", params={"cik": "123\x00456"})
    assert response.status_code == 422


def test_get_notes_empty_result_shape(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/notes", params={"cik": "0000000000"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}
