"""Contract test for `GET /api/v1/events` (system design §5, amended:
requires `cik` or `symbol`, keyset-paginated)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import pytest_asyncio
import seed
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

CIK = "9000000301"
SYMBOL = "ZTE"
CIK_OTHER = "9000000302"
SYMBOL_OTHER = "ZTEO"
CIK_SAME_DATE = "9000000303"
SYMBOL_SAME_DATE = "ZTESD"


@pytest_asyncio.fixture
async def events_fixture(app_writer_engine: AsyncEngine) -> AsyncIterator[None]:
    async with app_writer_engine.connect() as conn:
        await seed.insert_company(conn, cik=CIK, name="Zenith Test Events Co")
        await seed.insert_listing(conn, symbol=SYMBOL, cik=CIK)
        for day, kind, title in [
            (date(2024, 1, 5), "filing_10k", "10-K filed"),
            (date(2024, 3, 1), "cash_dividend", "Dividend declared"),
            (date(2024, 6, 15), "split", "2-for-1 split"),
        ]:
            await seed.insert_event(
                conn,
                cik=CIK,
                symbol=SYMBOL,
                event_date=day,
                kind=kind,
                title=title,
                source="test-seed",
                source_ref=f"{CIK}:{day.isoformat()}:{kind}",
            )

        await seed.insert_company(conn, cik=CIK_OTHER, name="Zenith Test Other Co")
        await seed.insert_listing(conn, symbol=SYMBOL_OTHER, cik=CIK_OTHER)

        # Two Events on the same date -- the id tiebreak must still give a
        # deterministic order and a working cursor.
        await seed.insert_company(conn, cik=CIK_SAME_DATE, name="Zenith Test Same Date Co")
        await seed.insert_listing(conn, symbol=SYMBOL_SAME_DATE, cik=CIK_SAME_DATE)
        same_day = date(2024, 5, 1)
        for kind, title in [("cash_dividend", "First"), ("filing_8k", "Second")]:
            await seed.insert_event(
                conn,
                cik=CIK_SAME_DATE,
                symbol=SYMBOL_SAME_DATE,
                event_date=same_day,
                kind=kind,
                title=title,
                source="test-seed",
                source_ref=f"{CIK_SAME_DATE}:{title}",
            )

    yield

    async with app_writer_engine.connect() as conn:
        await seed.cleanup_cik(conn, cik=CIK)
        await seed.cleanup_cik(conn, cik=CIK_OTHER)
        await seed.cleanup_cik(conn, cik=CIK_SAME_DATE)


def test_events_requires_cik_or_symbol(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events")
    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "https://stockticker.local/problems/events-requires-cik-or-symbol"


def test_events_by_cik_orders_most_recent_first(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": CIK})
    assert response.status_code == 200
    body = response.json()
    assert [item["kind"] for item in body["items"]] == ["split", "cash_dividend", "filing_10k"]
    assert body["next_cursor"] is None


def test_events_by_symbol_resolves_to_same_results(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"symbol": SYMBOL})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 3


def test_events_symbol_is_normalized(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"symbol": SYMBOL.lower()})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 3


def test_events_cik_and_symbol_agree_is_fine(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": CIK, "symbol": SYMBOL})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 3


def test_events_cik_and_symbol_disagree_is_422(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": CIK, "symbol": SYMBOL_OTHER})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/cik-symbol-mismatch"


def test_events_unknown_cik_is_404(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": "0000000000"})
    assert response.status_code == 404
    assert response.json()["type"] == "https://stockticker.local/problems/unknown-cik"


def test_events_unknown_symbol_is_404(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"symbol": "NOPE999"})
    assert response.status_code == 404
    assert response.json()["type"] == "https://stockticker.local/problems/unknown-symbol"


def test_events_from_after_to_is_422(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": CIK, "from": "2024-06-01", "to": "2024-01-01"})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-range"


def test_events_pagination_cursor_walks_all_pages(events_fixture: None, api_client: TestClient) -> None:
    first = api_client.get("/api/v1/events", params={"cik": CIK, "limit": 2}).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None

    second = api_client.get(
        "/api/v1/events", params={"cik": CIK, "limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    assert {item["id"] for item in first["items"]} & {item["id"] for item in second["items"]} == set()


def test_events_exact_limit_page_has_no_next_cursor(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": CIK, "limit": 3})
    body = response.json()
    assert len(body["items"]) == 3
    assert body["next_cursor"] is None


def test_events_same_date_events_paginate_deterministically(
    events_fixture: None, api_client: TestClient
) -> None:
    first = api_client.get("/api/v1/events", params={"cik": CIK_SAME_DATE, "limit": 1}).json()
    assert len(first["items"]) == 1
    assert first["next_cursor"] is not None

    second = api_client.get(
        "/api/v1/events",
        params={"cik": CIK_SAME_DATE, "limit": 1, "cursor": first["next_cursor"]},
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_events_unknown_kind_is_422(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": CIK, "kind": "not-a-kind"})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-event-kind"


def test_events_empty_result_for_cik_with_no_events(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": CIK_OTHER})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_events_cursor_with_null_id_is_422(events_fixture: None, api_client: TestClient) -> None:
    cursor = seed.encode_cursor({"event_date": "2024-01-01", "id": None})
    response = api_client.get("/api/v1/events", params={"cik": CIK, "cursor": cursor})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-cursor"


def test_events_cursor_with_list_id_is_422(events_fixture: None, api_client: TestClient) -> None:
    cursor = seed.encode_cursor({"event_date": "2024-01-01", "id": [1, 2]})
    response = api_client.get("/api/v1/events", params={"cik": CIK, "cursor": cursor})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-cursor"


def test_events_cursor_with_out_of_range_id_is_422(events_fixture: None, api_client: TestClient) -> None:
    cursor = seed.encode_cursor({"event_date": "2024-01-01", "id": 10**30})
    response = api_client.get("/api/v1/events", params={"cik": CIK, "cursor": cursor})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-cursor"


def test_events_garbage_cursor_is_422(events_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": CIK, "cursor": "not-base64-json!!"})
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-cursor"


def test_events_rejects_nul_byte_in_cik(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/events", params={"cik": "123\x00456"})
    assert response.status_code == 422
