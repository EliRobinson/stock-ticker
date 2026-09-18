"""`uv run python -m stockticker.evals`: run the Ask golden cases against a
running API, print the scorecard, and write `api/evals/results/<date>.md`.

It needs what the `api` service has: the Postgres passwords (reference SQL as
`ai_reader`, the ledger as `app_writer`) and `ANTHROPIC_API_KEY` (the judge).
The simplest way to get both is to run it in a one-off `api` container on the
running stack; the README's "AI quality" section has the command.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

from anthropic import AsyncAnthropic

from stockticker.ai.context import midnight_ny
from stockticker.ai.executor import AiReaderExecutor
from stockticker.ai.pricing import price_for
from stockticker.ai.spend import PostgresSpendLedger
from stockticker.config import get_settings
from stockticker.db import dispose_engines, get_ai_reader_engine, get_api_app_writer_engine
from stockticker.evals.cases import DEFAULT_CASES_PATH, RESULTS_DIR, Case, load_cases
from stockticker.evals.judge import JUDGE_MODEL, Judge
from stockticker.evals.report import RunInfo, markdown, results_path, scorecard
from stockticker.evals.runner import HttpAskApi, Runner
from stockticker.evals.sources import GuardedReferenceSource, LedgerUsageSource
from stockticker.timeutil import today_ny

DEFAULT_BUDGET_USD = Decimal("0.50")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m stockticker.evals", description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="The running API.")
    parser.add_argument(
        "--host-header",
        default=None,
        help="Host header to send, e.g. 127.0.0.1 when --api-url is http://api:8000.",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--only", default="", help="Comma-separated case ids to run.")
    parser.add_argument("--budget-usd", type=Decimal, default=DEFAULT_BUDGET_USD)
    parser.add_argument(
        "--backfilled-only",
        action="store_true",
        help="Run only cases whose companies have full price history loaded.",
    )
    parser.add_argument("--no-judge", action="store_true", help="Code checks only; no judge calls.")
    parser.add_argument(
        "--references-only",
        action="store_true",
        help="Compute and print every reference, then stop. Makes no model calls.",
    )
    parser.add_argument("--no-write", action="store_true", help="Do not write the results file.")
    return parser.parse_args(argv)


async def references_only(args: argparse.Namespace) -> int:
    source = GuardedReferenceSource(AiReaderExecutor(get_ai_reader_engine()))
    for case in _selected(args):
        for name, reference in case.references.items():
            try:
                rows = await source.rows(reference.sql)
            except Exception as error:
                print(f"{case.id}.{name}: ERROR {error}")
                continue
            held = "ok" if bool(rows) == (reference.expect == "rows") else "BLOCKED"
            print(f"{case.id}.{name}: {len(rows)} row(s), expect {reference.expect}: {held}")
            for row in rows[:5]:
                print(f"    {row}")
    return 0


def _selected(args: argparse.Namespace) -> list[Case]:
    cases = load_cases(args.cases)
    wanted = {case_id.strip() for case_id in args.only.split(",") if case_id.strip()}
    unknown = wanted - {case.id for case in cases}
    if unknown:
        raise SystemExit(f"unknown case ids: {', '.join(sorted(unknown))}")
    return [case for case in cases if not wanted or case.id in wanted]


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    cases = _selected(args)
    judge: Judge | None = None
    if not args.no_judge:
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
        price = price_for(JUDGE_MODEL)
        if not key or price is None:
            print("The judge needs ANTHROPIC_API_KEY. Pass --no-judge to run code checks only.")
            return 2
        judge = Judge(
            client=AsyncAnthropic(api_key=key, max_retries=1),
            ledger=PostgresSpendLedger(get_api_app_writer_engine()),
            price=price,
            spend_limit_usd=settings.ai_spend_limit_usd,
            daily_token_budget=settings.ai_daily_token_budget,
            day_start=midnight_ny,
        )
    async with HttpAskApi.connect(args.api_url, args.host_header) as api:
        before = await api.status()
        if not before.enabled:
            print(f"Ask is off (spend ${before.spend_usd} of ${before.limit_usd}). Nothing was run.")
            return 2
        runner = Runner(
            api=api,
            references=GuardedReferenceSource(AiReaderExecutor(get_ai_reader_engine())),
            usage=LedgerUsageSource(get_api_app_writer_engine()),
            judge=judge,
            budget_usd=args.budget_usd,
            backfilled_only=args.backfilled_only,
        )
        results = await runner.run(cases)
        after = await api.status()
    info = RunInfo(
        day=today_ny(),
        answer_model=settings.ai_model,
        judge_model=judge.model if judge else None,
        budget_usd=args.budget_usd,
        before=before,
        after=after,
        stopped=runner.stopped,
    )
    print(scorecard(results, info))
    if not args.no_write:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = results_path(RESULTS_DIR, info.day)
        path.write_text(markdown(results, info))
        print(f"\nWrote {path}")
    return 0


async def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        return await (references_only(args) if args.references_only else run(args))
    finally:
        await dispose_engines()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
