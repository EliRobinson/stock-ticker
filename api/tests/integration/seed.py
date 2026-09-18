"""Shared seed/cleanup helpers for the read-endpoint and Notes contract
tests (`tests/integration/test_*_api.py`).

Every helper here `COMMIT`s: the FastAPI app under test (`TestClient(app)`)
reads through its own connection pool (`get_app_writer_connection`), a
*different* Postgres session than whatever connection a fixture uses to set
up rows -- an uncommitted seed row is invisible to the app's session, so
there is no shortcut through a rolled-back transaction here. Every seeding
fixture must therefore also clean up what it inserted (`cleanup_cik`/
`cleanup_symbol` below), so repeated local runs against the same compose
Postgres stay repeatable and the "empty DB" contract tests still see an
empty result.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.ingest.edgar.parse import DEI_SHARES
from stockticker.ingest.watermarks import write_watermark
from stockticker.timeutil import NY_TZ


def trading_day_window(d: date) -> tuple[datetime, datetime]:
    return datetime.combine(d, time(9, 30), NY_TZ), datetime.combine(d, time(16, 0), NY_TZ)


def encode_cursor(payload: dict[str, Any]) -> str:
    """A cursor payload the app's own `decode_cursor` would accept -- for
    tests that need to hand-craft an invalid one (a bad type, an
    out-of-range value) that `stockticker.api.pagination.encode_cursor`
    itself would never produce."""
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


async def ensure_trading_days(conn: AsyncConnection, days: list[date]) -> None:
    for d in days:
        open_at, close_at = trading_day_window(d)
        await conn.execute(
            text(
                "INSERT INTO trading_days (trade_date, open_at, close_at) "
                "VALUES (:d, :open_at, :close_at) ON CONFLICT (trade_date) DO NOTHING"
            ),
            {"d": d, "open_at": open_at, "close_at": close_at},
        )
    await conn.commit()


async def insert_company(
    conn: AsyncConnection,
    *,
    cik: str,
    name: str,
    sector: str = "Technology",
    sub_industry: str | None = "Software",
    headquarters: str | None = "Testville, TS",
    date_added: date | None = None,
    is_active: bool = True,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO companies (cik, name, sector, sub_industry, headquarters, date_added, is_active) "
            "VALUES (:cik, :name, :sector, :sub_industry, :headquarters, :date_added, :is_active)"
        ),
        {
            "cik": cik,
            "name": name,
            "sector": sector,
            "sub_industry": sub_industry,
            "headquarters": headquarters,
            "date_added": date_added,
            "is_active": is_active,
        },
    )
    await conn.commit()


async def insert_listing(
    conn: AsyncConnection,
    *,
    symbol: str,
    cik: str,
    is_primary: bool = True,
    is_active: bool = True,
    first_bar_date: date | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO listings (symbol, cik, is_primary, is_active, first_bar_date) "
            "VALUES (:symbol, :cik, :is_primary, :is_active, :first_bar_date)"
        ),
        {
            "symbol": symbol,
            "cik": cik,
            "is_primary": is_primary,
            "is_active": is_active,
            "first_bar_date": first_bar_date,
        },
    )
    await conn.commit()


async def insert_bar(
    conn: AsyncConnection,
    *,
    symbol: str,
    trade_date: date,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: int,
    adj_close: Decimal,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO daily_bars "
            "(symbol, trade_date, open, high, low, close, volume, adj_close, source, ingested_at) "
            "VALUES (:symbol, :trade_date, :open, :high, :low, :close, :volume, :adj_close, "
            "'test-seed', now())"
        ),
        {
            "symbol": symbol,
            "trade_date": trade_date,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "adj_close": adj_close,
        },
    )
    await conn.commit()


async def insert_quote(
    conn: AsyncConnection, *, symbol: str, price: Decimal, observed_at: datetime, feed: str = "iex"
) -> None:
    await conn.execute(
        text(
            "INSERT INTO quotes (symbol, price, observed_at, fetched_at, feed) "
            "VALUES (:symbol, :price, :observed_at, now(), :feed)"
        ),
        {"symbol": symbol, "price": price, "observed_at": observed_at, "feed": feed},
    )
    await conn.commit()


async def insert_market_cap(
    conn: AsyncConnection,
    *,
    cik: str,
    trade_date: date,
    market_cap: Decimal,
    shares_used: int,
    shares_as_of: date,
    is_multi_class: bool = False,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO market_caps "
            "(cik, trade_date, market_cap, shares_used, shares_as_of, is_multi_class) "
            "VALUES (:cik, :trade_date, :market_cap, :shares_used, :shares_as_of, :is_multi_class)"
        ),
        {
            "cik": cik,
            "trade_date": trade_date,
            "market_cap": market_cap,
            "shares_used": shares_used,
            "shares_as_of": shares_as_of,
            "is_multi_class": is_multi_class,
        },
    )
    await conn.commit()


async def insert_event(
    conn: AsyncConnection,
    *,
    cik: str,
    symbol: str | None,
    event_date: date,
    kind: str,
    title: str,
    source: str,
    source_ref: str,
    details: dict[str, Any] | None = None,
) -> int:
    row = (
        await conn.execute(
            text(
                "INSERT INTO events (cik, symbol, event_date, kind, title, details, source, source_ref) "
                "VALUES (:cik, :symbol, :event_date, :kind, :title, CAST(:details AS jsonb), "
                ":source, :source_ref) "
                "RETURNING id"
            ),
            {
                "cik": cik,
                "symbol": symbol,
                "event_date": event_date,
                "kind": kind,
                "title": title,
                # asyncpg needs a JSON string for a jsonb bind param, not a
                # Python dict -- json.dumps + an explicit CAST, matching how
                # a jsonb literal would be sent over the wire.
                "details": json.dumps(details or {}),
                "source": source,
                "source_ref": source_ref,
            },
        )
    ).scalar_one()
    await conn.commit()
    return int(row)


async def cleanup_cik(conn: AsyncConnection, *, cik: str) -> None:
    """Deletes every row this module could have created for `cik`, in FK
    order, plus its Listings' `daily_bars`/`quotes`."""
    symbols = [
        row[0]
        for row in (
            await conn.execute(text("SELECT symbol FROM listings WHERE cik = :cik"), {"cik": cik})
        ).all()
    ]
    for symbol in symbols:
        await conn.execute(text("DELETE FROM daily_bars WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM quotes WHERE symbol = :symbol"), {"symbol": symbol})
    await conn.execute(text("DELETE FROM market_caps WHERE cik = :cik"), {"cik": cik})
    await conn.execute(text("DELETE FROM events WHERE cik = :cik"), {"cik": cik})
    await conn.execute(text("DELETE FROM notes WHERE cik = :cik"), {"cik": cik})
    await conn.execute(text("DELETE FROM listings WHERE cik = :cik"), {"cik": cik})
    await conn.execute(text("DELETE FROM share_class_rules WHERE cik = :cik"), {"cik": cik})
    await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
    await conn.commit()


async def cleanup_note(conn: AsyncConnection, *, note_id: Any) -> None:
    await conn.execute(text("DELETE FROM notes WHERE id = :id"), {"id": note_id})
    await conn.commit()


def new_symbol() -> str:
    return f"T{uuid.uuid4().hex[:6].upper()}"


class Scenario:
    """A Market Cap rebuild's Company/Listing/shares/splits, built up one
    call at a time (`tests/integration/test_market_caps_math.py`).

    Unlike every helper above, `Scenario`'s methods never commit: a test
    seeds a `Scenario` on its own connection, inside its own transaction,
    and rolls that transaction back at the end -- there is no separate app
    session here that needs the seed committed to see it.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def company(self, *, price_symbol: str | None = None, unit_ratio: str = "1") -> str:
        """A fresh Company. `price_symbol` also seeds a share_class_rules row,
        like the multi-class issuers in the migration."""
        cik = f"9{uuid.uuid4().int % 10**9:09d}"
        await self.conn.execute(
            text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test Co', 'Test')"), {"cik": cik}
        )
        if price_symbol is not None:
            await self.conn.execute(
                text(
                    "INSERT INTO share_class_rules (cik, price_symbol, shares_unit_ratio, note) "
                    "VALUES (:cik, :symbol, :ratio, 'test')"
                ),
                {"cik": cik, "symbol": price_symbol, "ratio": Decimal(unit_ratio)},
            )
        return cik

    async def listing(
        self,
        cik: str,
        symbol: str | None = None,
        *,
        primary: bool = True,
        active: bool = True,
        backfilled: bool = True,
        splits_synced: bool = True,
    ) -> str:
        symbol = symbol or new_symbol()
        if primary and active:
            await self.conn.execute(
                text("UPDATE listings SET is_primary = false WHERE cik = :cik AND symbol <> :symbol"),
                {"cik": cik, "symbol": symbol},
            )
        await self.conn.execute(
            text(
                "INSERT INTO listings (symbol, cik, is_primary, is_active, backfill_completed_at) "
                "VALUES (:symbol, :cik, :primary, :active, CASE WHEN :backfilled THEN now() END)"
            ),
            {"symbol": symbol, "cik": cik, "primary": primary, "active": active, "backfilled": backfilled},
        )
        if splits_synced:
            await write_watermark(self.conn, "corporate_actions_sync", f"bootstrapped:{symbol}", "2018-01-01")
        return symbol

    async def bars(self, symbol: str, closes: dict[str, str]) -> None:
        for day, close in closes.items():
            trade_date = date.fromisoformat(day)
            opens = datetime.combine(trade_date, time(13, 30), tzinfo=UTC)
            await self.conn.execute(
                text(
                    "INSERT INTO trading_days (trade_date, open_at, close_at) VALUES (:d, :o, :c) "
                    "ON CONFLICT (trade_date) DO NOTHING"
                ),
                {"d": trade_date, "o": opens, "c": opens + timedelta(hours=6, minutes=30)},
            )
            await self.conn.execute(
                text(
                    "INSERT INTO daily_bars (symbol, trade_date, open, high, low, close, volume, adj_close, "
                    "source, ingested_at) VALUES (:s, :d, :p, :p, :p, :p, 0, :p, 'test', now()) "
                    "ON CONFLICT (symbol, trade_date) DO UPDATE SET open = excluded.open, "
                    "high = excluded.high, low = excluded.low, close = excluded.close, "
                    "adj_close = excluded.adj_close"
                ),
                {"s": symbol, "d": trade_date, "p": Decimal(close)},
            )

    async def shares(
        self,
        cik: str,
        as_of: str,
        filed: str,
        shares: int,
        *,
        concept: str = DEI_SHARES,
        accession: str | None = None,
    ) -> None:
        await self.conn.execute(
            text(
                "INSERT INTO shares_outstanding "
                "(cik, as_of_date, concept, accession, form, filed_date, shares) "
                "VALUES (:cik, :as_of, :concept, :accession, '10-Q', :filed, :shares)"
            ),
            {
                "cik": cik,
                "as_of": date.fromisoformat(as_of),
                "concept": concept,
                "accession": accession or f"acc-{uuid.uuid4().hex[:10]}",
                "filed": date.fromisoformat(filed),
                "shares": shares,
            },
        )

    async def event(
        self, cik: str, symbol: str | None, kind: str, on: str, details: dict[str, Any] | None = None
    ) -> None:
        await self.conn.execute(
            text(
                "INSERT INTO events (cik, symbol, event_date, kind, title, details, source, source_ref) "
                "VALUES (:cik, :symbol, :on, :kind, 'test', CAST(:details AS jsonb), 'test', :ref)"
            ),
            {
                "cik": cik,
                "symbol": symbol,
                "on": date.fromisoformat(on),
                "kind": kind,
                "details": json.dumps(details or {}),
                "ref": uuid.uuid4().hex,
            },
        )

    async def caps(self, cik: str) -> dict[date, Any]:
        result = await self.conn.execute(
            text(
                "SELECT trade_date, market_cap, shares_used, shares_as_of, is_multi_class "
                "FROM market_caps WHERE cik = :cik ORDER BY trade_date"
            ),
            {"cik": cik},
        )
        return {row.trade_date: row for row in result}
