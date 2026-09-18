"""`market_caps_rebuild` (system design §3, "Market Cap rules").

    market_cap(c, d) = close(price Listing, d) x shares(c, d)

- **Price Listing.** `public.price_symbol(cik)` (the foundation's one copy
  of the rule): the `share_class_rules.price_symbol` Listing if it is
  active, else the active primary Listing. Read once, in `load_target`, and
  passed to the rebuild as `:price_symbol`.
- **Shares.** Point-in-time: the count from the latest filing with
  `filed_date <= d`; among counts filed the same day, the latest
  `as_of_date`, then `dei` before `us-gaap`. Multiplied by
  `shares_unit_ratio` (default 1) and by the product of split ratios with
  `anchor < ex_date <= d` (`ShareCount.anchor_date`, the one copy of that
  rule; SQL receives the anchor as data).
- **Splits** are the Company's `split`/`reverse_split` Events on the price
  Listing, on a retired ticker, or with no symbol. A split on another
  *active* class Listing is that class's, not the price Listing's. A split
  recorded under the old ticker before a rename (FISV before FI) still
  applies.
- **Multi-class issuers** (a `share_class_rules` row) use `us-gaap` counts
  only. Their `dei` cover count is either per class, which companyfacts
  omits, or a placeholder: Fox's only one is `1`. `is_multi_class` is true
  exactly for these.

A Company is skipped, and its rows are left as they are, when:

- it is inactive: its history is data and stays frozen;
- it has no active price Listing;
- its price Listing's backfill has not finished (after a ticker change the
  new Listing has no bars yet, and rebuilding would delete the history);
- its splits have not been synced yet: `corporate_actions_sync` has not
  written the `bootstrapped:{symbol}` watermark for the price Listing.

Sanity checks run in Python over each Company's counts, in filing order.
A rejected count is excluded, so the previous accepted count carries
forward:

- the count is 0;
- the count is dated after its own filing;
- the count differs by more than 40% from the previous accepted count, with
  no split, spin-off, or merger (an 8-K item 2.01) in between. If the next
  count agrees with the rejected one within 40%, the change was real: both
  are accepted and become the new baseline, so one rejection can never
  freeze every later count.

Failed items are reported only when they are new since the previous run,
so a permanent condition (Berkshire has no whole-company count) does not
make every run `partial`.

The rebuild itself is one SQL statement per Company: it upserts every
computable Trading Day and deletes rows that are no longer computable.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.edgar.parse import DEI_SHARES, FILING_KINDS, MERGER_ITEM, shares_key
from stockticker.ingest.events import SplitRatioError, split_ratio
from stockticker.ingest.job import FailedItem, JobContext, JobResult, JobSkipped
from stockticker.ingest.watermarks import read_watermark, symbols_with_watermark, write_watermark
from stockticker.logging import get_logger

logger = get_logger(__name__)

JOB_NAME = "market_caps_rebuild"
MAX_UNEXPLAINED_CHANGE = Decimal("0.40")
SPLIT_KINDS = ("split", "reverse_split")
SPIN_OFF_KIND = "spin_off"
NO_WHOLE_COMPANY_COUNT = "no_whole_company_count"
SPLITS_NOT_SYNCED = "splits_not_synced"
REPORTED_KEY = "reported_items"
FILING_8K_KIND = FILING_KINDS["8-K"]

# Written by corporate_actions_sync (#4) once a symbol's corporate actions
# have been fetched back to 2018.
CORPORATE_ACTIONS_JOB = "corporate_actions_sync"
BOOTSTRAPPED_PREFIX = "bootstrapped:"


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
        """Where the split window starts. A `dei` cover count is the number
        outstanding on its `as_of_date`; a `us-gaap` balance-sheet count is
        restated for every split before its `filed_date`."""
        return self.as_of_date if self.concept == DEI_SHARES else self.filed_date


def _filing_order(count: ShareCount) -> tuple[date, date, bool, str]:
    """The one ordering of share counts: by filing date, then as-of date,
    then `dei` over `us-gaap`, then accession. The sanity checks walk counts
    in this order, and the rebuild picks the greatest eligible count by it."""
    return (count.filed_date, count.as_of_date, count.concept == DEI_SHARES, count.accession)


@dataclass(frozen=True, slots=True)
class Split:
    ex_date: date
    ratio: Decimal  # new shares per old share: 4 for a 4-for-1, 0.1 for a 1-for-10


@dataclass(frozen=True, slots=True)
class Rejection:
    count: ShareCount
    reason: str


@dataclass(frozen=True, slots=True)
class PriceTarget:
    price_symbol: str | None
    unit_ratio: Decimal
    is_multi_class: bool
    backfilled: bool
    splits_synced: bool


def validate_counts(
    counts: Sequence[ShareCount], exemption_dates: Sequence[date]
) -> tuple[list[ShareCount], list[Rejection]]:
    """Apply the §3 sanity checks. `exemption_dates` are the dates of the
    Company's splits, reverse splits, spin-offs, and mergers: a jump with one
    of them in between is not suspicious."""
    ordered = sorted(counts, key=_filing_order)
    accepted: list[ShareCount] = []
    rejected: list[Rejection] = []
    baseline: ShareCount | None = None
    # The counts of the most recent filing that were rejected as jumps. A
    # later *filing* (not another count in the same one) that agrees with
    # them confirms the new level.
    jumped: list[ShareCount] = []
    for count in ordered:
        invalid = _invalid_reason(count)
        if invalid is not None:
            rejected.append(Rejection(count, invalid))
            continue
        jump = _jump_reason(count, baseline, exemption_dates)
        if jump is None:
            accepted.append(count)
            baseline, jumped = count, []
            continue
        confirms = (
            jumped
            and count.accession != jumped[-1].accession
            and _jump_reason(count, jumped[-1], exemption_dates) is None
        )
        if confirms:
            confirmed = {id(c) for c in jumped}
            rejected = [r for r in rejected if id(r.count) not in confirmed]
            accepted.extend((*jumped, count))
            baseline, jumped = count, []
            continue
        rejected.append(Rejection(count, jump))
        if not jumped or jumped[-1].accession != count.accession:
            jumped = []
        jumped.append(count)
    accepted.sort(key=_filing_order)
    return accepted, rejected


def _invalid_reason(count: ShareCount) -> str | None:
    if count.shares <= 0:
        return "shares outstanding is 0"
    if count.as_of_date > count.filed_date:
        return f"count dated {count.as_of_date}, after its filing on {count.filed_date}"
    return None


def _jump_reason(
    count: ShareCount, previous: ShareCount | None, exemption_dates: Sequence[date]
) -> str | None:
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
    WITH splits AS (
      SELECT * FROM unnest(CAST(:split_dates AS date[]), CAST(:split_ratios AS numeric[]))
        AS s(ex_date, ratio)
    ),
    accepted AS (
      SELECT * FROM unnest(CAST(:accepted_as_of AS date[]), CAST(:accepted_concept AS text[]),
                           CAST(:accepted_accession AS text[]), CAST(:accepted_anchor AS date[]),
                           CAST(:accepted_rank AS int[]))
        AS a(as_of_date, concept, accession, anchor_date, filing_rank)
    ),
    counts AS (
      SELECT s.as_of_date, s.filed_date, s.shares, a.anchor_date, a.filing_rank
      FROM shares_outstanding s
      JOIN accepted a USING (as_of_date, concept, accession)
      WHERE s.cik = :cik
    ),
    chosen AS (
      SELECT b.trade_date, b.close, cnt.shares, cnt.as_of_date, cnt.anchor_date
      FROM daily_bars b
      CROSS JOIN LATERAL (
        SELECT * FROM counts s
        WHERE s.as_of_date <= b.trade_date AND s.filed_date <= b.trade_date
        ORDER BY s.filing_rank DESC
        LIMIT 1
      ) cnt
      WHERE b.symbol = :price_symbol
    ),
    valued AS (
      SELECT ch.trade_date, ch.close, ch.as_of_date,
             round(
               ch.shares * CAST(:unit_ratio AS numeric) * COALESCE(
                 (SELECT exp(sum(ln(sp.ratio))) FROM splits sp
                   WHERE sp.ex_date > ch.anchor_date AND sp.ex_date <= ch.trade_date),
                 1)
             )::bigint AS shares_used
      FROM chosen ch
    ),
    upserted AS (
      INSERT INTO market_caps (cik, trade_date, market_cap, shares_used, shares_as_of, is_multi_class)
      SELECT :cik, v.trade_date, round(v.close * v.shares_used, 2), v.shares_used, v.as_of_date,
             CAST(:is_multi_class AS boolean)
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
    upserted: int = 0
    removed: int = 0
    rejections: list[Rejection] = field(default_factory=list)
    skipped: str | None = None  # why the Company was left untouched
    # No whole-company count on file (Berkshire, Fox, and News Corp report
    # per class only): the Company has no Market Cap, and that is reported,
    # not guessed.
    no_whole_company_count: bool = False


async def load_target(conn: AsyncConnection, cik: str) -> PriceTarget:
    row = (
        await conn.execute(
            text(
                """
                SELECT COALESCE(r.shares_unit_ratio, 1) AS unit_ratio,
                       r.cik IS NOT NULL AS is_multi_class,
                       l.symbol AS price_symbol,
                       l.backfill_completed_at IS NOT NULL AS backfilled
                FROM companies c
                LEFT JOIN share_class_rules r ON r.cik = c.cik
                LEFT JOIN listings l ON l.symbol = public.price_symbol(c.cik)
                WHERE c.cik = :cik
                """
            ),
            {"cik": cik},
        )
    ).one()
    synced = (
        bool(
            await symbols_with_watermark(conn, CORPORATE_ACTIONS_JOB, BOOTSTRAPPED_PREFIX, [row.price_symbol])
        )
        if row.price_symbol
        else False
    )
    return PriceTarget(
        price_symbol=row.price_symbol,
        unit_ratio=row.unit_ratio,
        is_multi_class=row.is_multi_class,
        backfilled=row.backfilled or False,
        splits_synced=synced,
    )


async def rebuild_company(conn: AsyncConnection, cik: str) -> CompanyRebuild:
    """Validate one Company's counts and rebuild its `market_caps` rows in
    one statement. Does not commit. Raises `SplitRatioError` if an applicable
    split has no usable ratio, before writing anything."""
    target = await load_target(conn, cik)
    if target.price_symbol is None:
        return CompanyRebuild(skipped="no active price Listing")
    if not target.backfilled:
        return CompanyRebuild(skipped=f"{target.price_symbol} backfill not finished")
    if not target.splits_synced:
        return CompanyRebuild(skipped=SPLITS_NOT_SYNCED)

    counts = await _load_counts(conn, cik, us_gaap_only=target.is_multi_class)
    splits, exemption_dates = await _load_corporate_events(conn, cik, target.price_symbol)
    accepted, rejections = validate_counts(counts, exemption_dates)
    row = (
        await conn.execute(
            REBUILD_SQL,
            {
                "cik": cik,
                "price_symbol": target.price_symbol,
                "unit_ratio": target.unit_ratio,
                "is_multi_class": target.is_multi_class,
                "split_dates": [split.ex_date for split in splits],
                "split_ratios": [split.ratio for split in splits],
                "accepted_as_of": [count.as_of_date for count in accepted],
                "accepted_concept": [count.concept for count in accepted],
                "accepted_accession": [count.accession for count in accepted],
                "accepted_anchor": [count.anchor_date for count in accepted],
                "accepted_rank": list(range(len(accepted))),
            },
        )
    ).one()
    return CompanyRebuild(
        upserted=row.upserted,
        removed=row.removed,
        rejections=rejections,
        no_whole_company_count=not counts,
    )


async def _load_counts(conn: AsyncConnection, cik: str, *, us_gaap_only: bool) -> list[ShareCount]:
    result = await conn.execute(
        text(
            "SELECT as_of_date, filed_date, concept, accession, shares FROM shares_outstanding "
            "WHERE cik = :cik AND (NOT :us_gaap_only OR concept <> :dei)"
        ),
        {"cik": cik, "us_gaap_only": us_gaap_only, "dei": DEI_SHARES},
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


async def _load_corporate_events(
    conn: AsyncConnection, cik: str, price_symbol: str
) -> tuple[list[Split], list[date]]:
    """The splits that apply to the price Listing (for the share factor),
    and the dates of every split, spin-off, and merger of the Company (for
    the jump check)."""
    result = await conn.execute(
        text(
            """
            SELECT e.kind, e.event_date, e.details,
                   e.symbol IS NULL OR e.symbol = :price_symbol OR NOT EXISTS (
                     SELECT 1 FROM listings l WHERE l.cik = e.cik AND l.is_active AND l.symbol = e.symbol
                   ) AS applies_to_price
            FROM events e
            WHERE e.cik = :cik
              AND (e.kind = ANY(:exempting_kinds)
                   OR (e.kind = :filing_8k
                       AND e.details -> 'items' @> jsonb_build_array(CAST(:merger_item AS text))))
            """
        ),
        {
            "cik": cik,
            "price_symbol": price_symbol,
            "exempting_kinds": [*SPLIT_KINDS, SPIN_OFF_KIND],
            "filing_8k": FILING_8K_KIND,
            "merger_item": MERGER_ITEM,
        },
    )
    splits: list[Split] = []
    exemption_dates: list[date] = []
    for row in result:
        exemption_dates.append(row.event_date)
        if row.kind in SPLIT_KINDS and row.applies_to_price:
            splits.append(Split(ex_date=row.event_date, ratio=split_ratio(row.details)))
    return splits, exemption_dates


async def _companies_to_rebuild(conn: AsyncConnection) -> list[str]:
    result = await conn.execute(
        text(
            "SELECT DISTINCT c.cik FROM companies c JOIN listings l ON l.cik = c.cik "
            "WHERE c.is_active AND l.is_active ORDER BY c.cik"
        )
    )
    return [row.cik for row in result]


async def market_caps_rebuild(ctx: JobContext) -> JobResult:
    return await run_market_caps_rebuild(ctx.engine)


async def run_market_caps_rebuild(engine: AsyncEngine) -> JobResult:
    result = JobResult()
    data_items: list[FailedItem] = []
    async with engine.connect() as conn:
        ciks = await _companies_to_rebuild(conn)
        await conn.commit()
        if not ciks:
            raise JobSkipped("no active Companies with an active Listing")
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
            if rebuilt.skipped == SPLITS_NOT_SYNCED:
                data_items.append(FailedItem(key=cik, error=SPLITS_NOT_SYNCED))
            elif rebuilt.skipped:
                logger.debug("market_caps_rebuild.skipped", cik=cik, reason=rebuilt.skipped)
            if rebuilt.no_whole_company_count:
                data_items.append(FailedItem(key=cik, error=NO_WHOLE_COMPANY_COUNT))
            data_items.extend(
                FailedItem(key=f"{cik}:{rejection.count.key}", error=rejection.reason)
                for rejection in rebuilt.rejections
            )
        result.failed_items.extend(await only_new_items(conn, data_items))
        await conn.commit()
    logger.info(
        "market_caps_rebuild.done",
        companies=len(ciks),
        rows_written=result.rows_written,
        data_items=len(data_items),
    )
    return result


async def only_new_items(conn: AsyncConnection, items: Sequence[FailedItem]) -> list[FailedItem]:
    """The items not already reported by the previous run; remembers this
    run's full set for the next one. Does not commit."""
    previous = set(json.loads(await read_watermark(conn, JOB_NAME, REPORTED_KEY) or "[]"))
    current = sorted({f"{item.key}\t{item.error}" for item in items})
    await write_watermark(conn, JOB_NAME, REPORTED_KEY, json.dumps(current))
    return [item for item in items if f"{item.key}\t{item.error}" not in previous]
