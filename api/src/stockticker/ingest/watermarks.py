"""Per-job key/value state in `ingest_watermarks`. None of these commit."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def read_watermarks(conn: AsyncConnection, job: str, prefix: str = "") -> dict[str, str]:
    """Every key of `job` starting with `prefix`, prefix removed."""
    result = await conn.execute(
        text("SELECT key, value FROM ingest_watermarks WHERE job = :job AND starts_with(key, :prefix)"),
        {"job": job, "prefix": prefix},
    )
    return {row.key.removeprefix(prefix): row.value for row in result}


async def read_watermark(conn: AsyncConnection, job: str, key: str) -> str | None:
    value: str | None = await conn.scalar(
        text("SELECT value FROM ingest_watermarks WHERE job = :job AND key = :key"),
        {"job": job, "key": key},
    )
    return value


async def write_watermark(conn: AsyncConnection, job: str, key: str, value: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO ingest_watermarks (job, key, value, updated_at) VALUES (:job, :key, :value, now()) "
            "ON CONFLICT (job, key) DO UPDATE SET value = excluded.value, updated_at = now()"
        ),
        {"job": job, "key": key, "value": value},
    )


async def delete_watermarks(conn: AsyncConnection, job: str, keys: Sequence[str]) -> None:
    if keys:
        await conn.execute(
            text("DELETE FROM ingest_watermarks WHERE job = :job AND key = ANY(:keys)"),
            {"job": job, "keys": list(keys)},
        )


async def symbols_with_watermark(
    conn: AsyncConnection, job: str, prefix: str, symbols: Sequence[str]
) -> set[str]:
    """Which of `symbols` have a `{prefix}{symbol}` key under `job`."""
    if not symbols:
        return set()
    result = await conn.execute(
        text("SELECT key FROM ingest_watermarks WHERE job = :job AND key = ANY(:keys)"),
        {"job": job, "keys": [prefix + symbol for symbol in symbols]},
    )
    return {row.key.removeprefix(prefix) for row in result}
