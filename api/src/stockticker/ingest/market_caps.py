"""`market_caps_rebuild` (system design §3, "Market Cap rules").

    market_cap(c, d) = close(price Listing, d) x shares(c, d)

- **Price Listing.** `share_class_rules.price_symbol` when a rule exists,
  else the primary Listing. Only an active Listing prices a Company, so a
  retired ticker never adds to its value.
- **Shares.** The count with the latest `as_of_date <= d`; ties go to the
  latest `filed_date`, then `dei` before `us-gaap`. Multiplied by
  `shares_unit_ratio` (default 1) and by the product of the price Listing's
  split ratios with `anchor < ex_date <= d`.
- `is_multi_class` is true exactly when the Company has a
  `share_class_rules` row.

Two deliberate departures from §3 as written. Both stop EDGAR restatements
from leaking into the past. Alphabet's 2022 20-for-1 split is the worked
case (`tests/integration/test_market_caps_math.py`):

1. **No lookahead.** A count is eligible for `d` only once it has been filed
   (`filed_date <= d`). Otherwise a comparative restated after a split (e.g.
   Alphabet's 2021-12-31 count, re-reported post-split in July 2022) would
   value pre-split prices with post-split shares.
2. **Split anchor.** The split window starts at the count's *anchor*: its
   `as_of_date` for a `dei` cover-page count (the count on that day, in that
   day's units), but its `filed_date` for a `us-gaap` balance-sheet count,
   because financial statements restate share counts for any split that
   happens before they are issued.

Sanity checks run in Python over each Company's counts before the rebuild,
in filing order. Each rejected count is a failed item and is excluded from
the rebuild, so the previous accepted count carries forward:

- the count is 0;
- the count is dated after its own filing;
- the count differs by more than 40% from the previous accepted count, with
  no split, spin-off, or merger (an 8-K item 2.01) in between.

The rebuild itself is one SQL statement per Company: it upserts every
computable Trading Day and deletes rows that are no longer computable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.edgar.parse import DEI_SHARES, MERGER_ITEM, shares_key
from stockticker.ingest.job import FailedItem, JobContext, JobResult, JobSkipped
from stockticker.logging import get_logger

logger = get_logger(__name__)

MAX_UNEXPLAINED_CHANGE = Decimal("0.40")
SPLIT_KINDS = ("split", "reverse_split")


class SplitRatioError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ShareCount:
    as_of_date: date
    filed_date: date
    concept: str
    accession: str
    shares: int

    @property
    def key(self) -> str:
        return shares_key(self.as_of_date, self.concept, self.accession)

    @property
    def anchor_date(self) -> date:
        return self.as_of_date if self.concept == DEI_SHARES else self.filed_date


@dataclass(frozen=True, slots=True)
class Split:
    ex_date: date
    ratio: Decimal  # new shares per old share: 4 for a 4-for-1, 0.1 for a 1-for-10


@dataclass(frozen=True, slots=True)
class Rejection:
    count: ShareCount
    reason: str


def split_ratio(kind: str, details: dict[str, Any]) -> Decimal:
    """New shares per old share, from a split Event's `details`: either
    `ratio`, or Alpaca's `new_rate` / `old_rate`. A reverse split always
    reduces the count, so a `ratio` above 1 on one (1-for-10 written as 10)
    is inverted."""
    try:
        if details.get("ratio") is not None:
            ratio = Decimal(str(details["ratio"]))
        else:
            ratio = Decimal(str(details["new_rate"])) / Decimal(str(details["old_rate"]))
    except (KeyError, InvalidOperation, ZeroDivisionError) as exc:
        raise SplitRatioError(f"no usable split ratio in {details!r}") from exc
    if ratio <= 0:
        raise SplitRatioError(f"split ratio must be positive, got {ratio}")
    if kind == "reverse_split" and ratio > 1:
        ratio = 1 / ratio
    return ratio


def validate_counts(
    counts: Sequence[ShareCount], exemption_dates: Sequence[date]
) -> tuple[list[ShareCount], list[Rejection]]:
    """Apply the §3 sanity checks. `exemption_dates` are the dates of the
    Company's splits, reverse splits, spin-offs, and mergers: a jump with one
    of them in between is not suspicious."""
    ordered = sorted(
        counts,
        key=lambda c: (c.filed_date, c.as_of_date, c.concept != DEI_SHARES, c.accession),
    )
    accepted: list[ShareCount] = []
    rejected: list[Rejection] = []
    previous: ShareCount | None = None
    for count in ordered:
        reason = _rejection_reason(count, previous, exemption_dates)
        if reason is not None:
            rejected.append(Rejection(count, reason))
            continue
        accepted.append(count)
        previous = count
    return accepted, rejected


def _rejection_reason(
    count: ShareCount, previous: ShareCount | None, exemption_dates: Sequence[date]
) -> str | None:
    if count.shares <= 0:
        return "shares outstanding is 0"
    if count.as_of_date > count.filed_date:
        return f"count dated {count.as_of_date}, after its filing on {count.filed_date}"
    if previous is None:
        return None
    change = abs(Decimal(count.shares - previous.shares)) / Decimal(previous.shares)
    if change <= MAX_UNEXPLAINED_CHANGE:
        return None
    window_start = min(previous.as_of_date, count.as_of_date)
    window_end = max(previous.filed_date, count.filed_date)
    if any(window_start < day <= window_end for day in exemption_dates):
        return None
    return (
        f"count changed {change:.0%} from {previous.shares} (as of {previous.as_of_date}) "
        f"to {count.shares} with no split, spin-off, or merger in between"
    )


REBUILD_SQL = text(
    """
    WITH target AS (
      SELECT c.cik,
             COALESCE(r.shares_unit_ratio, 1) AS unit_ratio,
             r.cik IS NOT NULL AS is_multi_class,
             COALESCE(
               (SELECT l.symbol FROM listings l
                 WHERE l.cik = c.cik AND l.is_active AND l.symbol = r.price_symbol),
               (SELECT l.symbol FROM listings l
                 WHERE l.cik = c.cik AND l.is_active AND l.is_primary)
             ) AS price_symbol
      FROM companies c
      LEFT JOIN share_class_rules r ON r.cik = c.cik
      WHERE c.cik = :cik
    ),
    splits AS (
      SELECT * FROM unnest(CAST(:split_dates AS date[]), CAST(:split_ratios AS numeric[]))
        AS s(ex_date, ratio)
    ),
    accepted AS (
      SELECT * FROM unnest(CAST(:accepted_as_of AS date[]), CAST(:accepted_concept AS text[]),
                           CAST(:accepted_accession AS text[]))
        AS a(as_of_date, concept, accession)
    ),
    counts AS (
      SELECT s.as_of_date, s.filed_date, s.concept, s.accession, s.shares,
             CASE WHEN s.concept = :dei THEN s.as_of_date ELSE s.filed_date END AS anchor_date
      FROM shares_outstanding s
      JOIN accepted a USING (as_of_date, concept, accession)
      WHERE s.cik = :cik
    ),
    chosen AS (
      SELECT b.trade_date, b.close, cnt.shares, cnt.as_of_date, cnt.anchor_date
      FROM target t
      JOIN daily_bars b ON b.symbol = t.price_symbol
      CROSS JOIN LATERAL (
        SELECT * FROM counts s
        WHERE s.as_of_date <= b.trade_date AND s.filed_date <= b.trade_date
        ORDER BY s.as_of_date DESC, s.filed_date DESC, (s.concept = :dei) DESC, s.accession DESC
        LIMIT 1
      ) cnt
    ),
    valued AS (
      SELECT ch.trade_date, ch.close, ch.as_of_date, t.is_multi_class,
             round(
               ch.shares * t.unit_ratio * COALESCE(
                 (SELECT exp(sum(ln(sp.ratio))) FROM splits sp
                   WHERE sp.ex_date > ch.anchor_date AND sp.ex_date <= ch.trade_date),
                 1)
             )::bigint AS shares_used
      FROM chosen ch CROSS JOIN target t
    ),
    upserted AS (
      INSERT INTO market_caps (cik, trade_date, market_cap, shares_used, shares_as_of, is_multi_class)
      SELECT :cik, v.trade_date, round(v.close * v.shares_used, 2), v.shares_used, v.as_of_date,
             v.is_multi_class
      FROM valued v
      ON CONFLICT (cik, trade_date) DO UPDATE SET
        market_cap = excluded.market_cap, shares_used = excluded.shares_used,
        shares_as_of = excluded.shares_as_of, is_multi_class = excluded.is_multi_class
      WHERE (market_caps.market_cap, market_caps.shares_used, market_caps.shares_as_of,
             market_caps.is_multi_class)
            IS DISTINCT FROM (excluded.market_cap, excluded.shares_used, excluded.shares_as_of,
                              excluded.is_multi_class)
      RETURNING 1
    ),
    removed AS (
      DELETE FROM market_caps m
      WHERE m.cik = :cik AND NOT EXISTS (SELECT 1 FROM valued v WHERE v.trade_date = m.trade_date)
      RETURNING 1
    )
    SELECT (SELECT count(*) FROM upserted) AS upserted, (SELECT count(*) FROM removed) AS removed
    """
)


@dataclass(slots=True)
class CompanyRebuild:
    upserted: int
    removed: int
    rejections: list[Rejection]


async def rebuild_company(conn: AsyncConnection, cik: str) -> CompanyRebuild:
    """Validate one Company's counts and rebuild its `market_caps` rows in
    one statement. Does not commit. Raises `SplitRatioError` if a split on
    the price Listing has no usable ratio, before writing anything."""
    counts = await _load_counts(conn, cik)
    splits, exemption_dates = await _load_corporate_events(conn, cik)
    accepted, rejections = validate_counts(counts, exemption_dates)
    row = (
        await conn.execute(
            REBUILD_SQL,
            {
                "cik": cik,
                "dei": DEI_SHARES,
                "split_dates": [split.ex_date for split in splits],
                "split_ratios": [split.ratio for split in splits],
                "accepted_as_of": [count.as_of_date for count in accepted],
                "accepted_concept": [count.concept for count in accepted],
                "accepted_accession": [count.accession for count in accepted],
            },
        )
    ).one()
    return CompanyRebuild(upserted=row.upserted, removed=row.removed, rejections=rejections)


async def _load_counts(conn: AsyncConnection, cik: str) -> list[ShareCount]:
    result = await conn.execute(
        text(
            "SELECT as_of_date, filed_date, concept, accession, shares FROM shares_outstanding "
            "WHERE cik = :cik"
        ),
        {"cik": cik},
    )
    return [
        ShareCount(
            as_of_date=row.as_of_date,
            filed_date=row.filed_date,
            concept=row.concept,
            accession=row.accession,
            shares=row.shares,
        )
        for row in result
    ]


async def _load_corporate_events(conn: AsyncConnection, cik: str) -> tuple[list[Split], list[date]]:
    """Splits on the price Listing (for the share factor), and the dates of
    every split, spin-off, and merger of the Company (for the jump check)."""
    result = await conn.execute(
        text(
            """
            WITH price AS (
              SELECT COALESCE(
                (SELECT l.symbol FROM listings l JOIN share_class_rules r ON r.cik = l.cik
                  WHERE l.cik = :cik AND l.is_active AND l.symbol = r.price_symbol),
                (SELECT l.symbol FROM listings l WHERE l.cik = :cik AND l.is_active AND l.is_primary)
              ) AS symbol
            )
            SELECT e.kind, e.event_date, e.details, e.symbol = (SELECT symbol FROM price) AS on_price
            FROM events e
            WHERE e.cik = :cik
              AND (e.kind IN ('split', 'reverse_split', 'spin_off')
                   OR (e.kind = 'filing_8k'
                       AND e.details -> 'items' @> jsonb_build_array(CAST(:merger_item AS text))))
            """
        ),
        {"cik": cik, "merger_item": MERGER_ITEM},
    )
    splits: list[Split] = []
    exemption_dates: list[date] = []
    for row in result:
        exemption_dates.append(row.event_date)
        if row.kind in SPLIT_KINDS and row.on_price:
            splits.append(Split(ex_date=row.event_date, ratio=split_ratio(row.kind, row.details)))
    return splits, exemption_dates


async def _companies_to_rebuild(conn: AsyncConnection) -> list[str]:
    result = await conn.execute(
        text("SELECT cik FROM listings WHERE is_active UNION SELECT cik FROM market_caps ORDER BY cik")
    )
    return [row.cik for row in result]


async def market_caps_rebuild(ctx: JobContext) -> JobResult:
    return await run_market_caps_rebuild(ctx.engine)


async def run_market_caps_rebuild(engine: AsyncEngine) -> JobResult:
    result = JobResult()
    async with engine.connect() as conn:
        ciks = await _companies_to_rebuild(conn)
        await conn.commit()
        if not ciks:
            raise JobSkipped("no active Listings and no Market Cap rows")
        for cik in ciks:
            try:
                rebuilt = await rebuild_company(conn, cik)
                await conn.commit()
            except (SplitRatioError, DBAPIError) as exc:
                if isinstance(exc, DBAPIError) and exc.connection_invalidated:
                    raise  # the connection is gone; every later Company would fail the same way
                await conn.rollback()
                result.failed_items.append(FailedItem(key=cik, error=f"rebuild skipped: {exc}"))
                continue
            result.rows_written += rebuilt.upserted + rebuilt.removed
            result.failed_items.extend(
                FailedItem(key=f"{cik}:{rejection.count.key}", error=rejection.reason)
                for rejection in rebuilt.rejections
            )
    logger.info("market_caps_rebuild.done", companies=len(ciks), rows_written=result.rows_written)
    return result
