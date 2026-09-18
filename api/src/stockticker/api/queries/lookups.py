"""Existence/resolution probes shared by `/events` and `/notes` -- both
need "does this cik exist" and `/events` additionally needs "what cik does
this symbol belong to"."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_CIK_EXISTS_QUERY = text("SELECT 1 FROM companies WHERE cik = :cik")
_SYMBOL_TO_CIK_QUERY = text("SELECT cik FROM listings WHERE symbol = :symbol")


async def cik_exists(conn: AsyncConnection, *, cik: str) -> bool:
    return (await conn.scalar(_CIK_EXISTS_QUERY, {"cik": cik})) is not None


async def symbol_cik(conn: AsyncConnection, *, symbol: str) -> str | None:
    cik: str | None = await conn.scalar(_SYMBOL_TO_CIK_QUERY, {"symbol": symbol})
    return cik
