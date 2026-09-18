"""The eval runner, its database adapters, and the scorecard. The API, the
database, and the judge are fakes; the HTTP client is exercised against a
mock transport that speaks the real stream protocol."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from ai_fakes import FakeExecutor, result

from stockticker.ai.guard import GuardError
from stockticker.evals.cases import DEFAULT_CASES_PATH, Case, SeedNote, load_cases
from stockticker.evals.judge import JudgeError, JudgeResult, Verdict
from stockticker.evals.report import RunInfo, markdown, results_path, scorecard, totals
from stockticker.evals.runner import (
    ApiStatus,
    HttpAskApi,
    Outcome,
    Runner,
    UsageRow,
    backfilled_sql,
    parse_status,
)
from stockticker.evals.sources import GuardedReferenceSource
from stockticker.evals.transcript import Transcript

GOLDEN = Path(__file__).parent / "golden"
ANSWER_MODEL = "claude-sonnet-5"
JUDGE = "claude-haiku-4-5"
STATUS = ApiStatus(Decimal("0.10"), Decimal("5"), True, 503, 503)


def case(**overrides: Any) -> Case:
    spec: dict[str, Any] = {
        "id": "top",
        "question": "Largest company?",
        "covers": "a test",
        "references": {"top": {"sql": "SELECT name FROM ai.companies"}},
        "checks": [
            {"kind": "completed"},
            {"kind": "tickers_present", "reference": "top", "symbol_column": "name", "min_hits": 1},
        ],
        "judge": ["no_invented_numbers"],
    }
    spec.update(overrides)
    return Case.model_validate(spec)


def usage(model: str, cost: str) -> UsageRow:
    return UsageRow(model, 1000, 0, 500, 100, Decimal(cost))


class FakeApi:
    def __init__(self, transcript: Transcript | Exception, *, cost: str = "0.02") -> None:
        self.transcript = transcript
        self.questions: list[str] = []
        self.notes: dict[uuid.UUID, SeedNote] = {}
        self.deleted: list[uuid.UUID] = []
        self.usage: FakeUsage | None = None
        self.cost = cost

    async def ask(self, question: str) -> Transcript:
        self.questions.append(question)
        if self.usage is not None:
            self.usage.rows.append(usage(ANSWER_MODEL, self.cost))
        if isinstance(self.transcript, Exception):
            raise self.transcript
        return self.transcript

    async def put_note(self, note_id: uuid.UUID, note: SeedNote) -> None:
        self.notes[note_id] = note

    async def delete_note(self, note_id: uuid.UUID) -> None:
        self.deleted.append(note_id)

    async def status(self) -> ApiStatus:
        return STATUS


class FakeReferences:
    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.by_sql = rows
        self.queries: list[str] = []

    async def rows(self, sql: str) -> list[dict[str, Any]]:
        self.queries.append(sql)
        for key, rows in self.by_sql.items():
            if key in sql:
                return rows
        return []


class FakeUsage:
    def __init__(self) -> None:
        self.rows: list[UsageRow] = []

    async def watermark(self) -> int:
        return len(self.rows)

    async def since(self, watermark: int) -> list[UsageRow]:
        return self.rows[watermark:]


class FakeJudge:
    model = JUDGE

    def __init__(self, usage_source: FakeUsage, *, passed: bool = True, error: bool = False) -> None:
        self.usage = usage_source
        self.passed = passed
        self.error = error

    async def grade(self, question: str, transcript: Transcript, criteria: Sequence[Any]) -> JudgeResult:
        self.usage.rows.append(usage(JUDGE, "0.003"))
        if self.error:
            raise JudgeError("unreadable")
        verdicts = [Verdict(c, self.passed, "reason") for c in criteria]
        return JudgeResult(verdicts, usage=None, cost_usd=Decimal("0.003"))  # type: ignore[arg-type]


def good_answer(text: str = "Apple Inc. is largest.") -> Transcript:
    return Transcript(texts=[text], steps=1, finish_reason="stop", done=True)


def runner(
    api: FakeApi,
    references: FakeReferences | None = None,
    *,
    judge_passes: bool = True,
    judge_error: bool = False,
    budget: str = "0.50",
    backfilled_only: bool = False,
) -> tuple[Runner, FakeUsage]:
    usage_source = FakeUsage()
    api.usage = usage_source
    return (
        Runner(
            api=api,
            references=references or FakeReferences({"ai.companies": [{"name": "Apple Inc."}]}),
            usage=usage_source,
            judge=FakeJudge(usage_source, passed=judge_passes, error=judge_error),
            budget_usd=Decimal(budget),
            backfilled_only=backfilled_only,
        ),
        usage_source,
    )


async def test_a_good_answer_passes_and_its_spend_is_split_by_model() -> None:
    run, _ = runner(FakeApi(good_answer()))
    [res] = await run.run([case()])
    assert res.outcome is Outcome.PASS
    assert res.answer_spend.cost_usd == Decimal("0.02")
    assert res.judge_spend.cost_usd == Decimal("0.003")
    assert res.spend.input_tokens == 3000
    assert run.spent_usd == Decimal("0.023")


async def test_a_failed_check_or_judge_verdict_fails_the_case() -> None:
    run, _ = runner(FakeApi(good_answer("Microsoft is largest.")))
    [res] = await run.run([case()])
    assert res.outcome is Outcome.FAIL
    assert any(f.startswith("tickers_present") for f in res.failures)

    run, _ = runner(FakeApi(good_answer()), judge_passes=False)
    [res] = await run.run([case()])
    assert res.outcome is Outcome.FAIL
    assert res.failures == ["judge no_invented_numbers: reason"]


async def test_a_judge_error_fails_the_criterion_instead_of_crashing() -> None:
    run, _ = runner(FakeApi(good_answer()), judge_error=True)
    [res] = await run.run([case()])
    assert res.outcome is Outcome.FAIL
    assert "judge error" in res.failures[0]


async def test_a_case_with_missing_data_is_blocked_and_never_asked() -> None:
    api = FakeApi(good_answer())
    run, _ = runner(api, FakeReferences({}))
    [res] = await run.run([case()])
    assert res.outcome is Outcome.BLOCKED
    assert "no rows" in res.reason
    assert api.questions == []


async def test_an_expect_empty_precondition_that_fails_blocks_the_case() -> None:
    api = FakeApi(good_answer())
    references = {"gone": {"sql": "SELECT 1 FROM ai.market_caps", "expect": "empty"}}
    run, _ = runner(api, FakeReferences({"ai.market_caps": [{"x": 1}]}))
    [res] = await run.run([case(references=references, checks=[{"kind": "completed"}])])
    assert res.outcome is Outcome.BLOCKED
    assert "expected no rows" in res.reason


async def test_a_failing_reference_query_blocks_the_case() -> None:
    class Broken(FakeReferences):
        async def rows(self, sql: str) -> list[dict[str, Any]]:
            raise GuardError("not allowed")

    run, _ = runner(FakeApi(good_answer()), Broken({}))
    [res] = await run.run([case()])
    assert res.outcome is Outcome.BLOCKED
    assert "not allowed" in res.reason


async def test_seeded_notes_are_deleted_even_when_the_request_fails() -> None:
    api = FakeApi(httpx.ConnectError("refused"))
    note = {"start_date": "2024-03-04", "end_date": "2024-03-08", "body": "Frothy."}
    run, _ = runner(api)
    [res] = await run.run([case(setup={"notes": [note]})])
    assert res.outcome is Outcome.ERROR
    assert "refused" in res.reason
    assert list(api.notes) == api.deleted
    assert len(api.deleted) == 1
    assert res.answer_spend.cost_usd == Decimal("0.02")


async def test_the_budget_stops_the_run_before_it_is_exceeded() -> None:
    api = FakeApi(good_answer(), cost="0.15")
    run, _ = runner(api, budget="0.50")
    results = await run.run([case(id=f"c{i}") for i in range(4)])
    assert [r.outcome for r in results] == [Outcome.PASS, Outcome.PASS, Outcome.SKIPPED, Outcome.SKIPPED]
    assert len(api.questions) == 2
    assert run.spent_usd <= Decimal("0.50")
    assert "budget" in run.stopped


async def test_backfilled_only_skips_cases_whose_data_is_not_loaded() -> None:
    references = FakeReferences(
        {"IN ('AAPL', 'ZTS')": [{"symbol": "AAPL"}], "ai.companies": [{"name": "Apple Inc."}]}
    )
    api = FakeApi(good_answer())
    run, _ = runner(api, references, backfilled_only=True)
    results = await run.run(
        [
            case(id="apple", companies=["AAPL"]),
            case(id="zoetis", companies=["ZTS"]),
            case(id="everyone", needs_full_backfill=True),
        ]
    )
    assert [r.outcome for r in results] == [Outcome.PASS, Outcome.SKIPPED, Outcome.SKIPPED]
    assert "ZTS" in results[1].reason
    assert api.questions == ["Largest company?"]


def test_backfilled_sql_refuses_anything_but_a_ticker() -> None:
    assert "IN ('AAPL', 'BRK.B')" in backfilled_sql(["AAPL", "BRK.B"])
    with pytest.raises(ValueError):
        backfilled_sql(["AAPL'); DROP TABLE x; --"])


# --- the HTTP client -------------------------------------------------------------


async def test_http_client_streams_chat_and_manages_notes() -> None:
    seen: list[httpx.Request] = []
    body = (GOLDEN / "normal_answer_with_table.sse").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/v1/chat":
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json={"ai": {"spend_usd": 0.12, "limit_usd": 5.0, "enabled": True}})
        return httpx.Response(204 if request.method == "DELETE" else 200, json={})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://api:8000", headers={"Host": "127.0.0.1"}
    )
    async with client:
        api = HttpAskApi(client)
        transcript = await api.ask("Top 2?")
        note_id = uuid.uuid4()
        await api.put_note(
            note_id, SeedNote(start_date=date(2024, 3, 4), end_date=date(2024, 3, 4), body="x")
        )
        await api.delete_note(note_id)
        status = await api.status()

    assert transcript.completed and len(transcript.views) == 1
    chat = json.loads(seen[0].content)
    assert chat["messages"][0]["parts"] == [{"type": "text", "text": "Top 2?"}]
    assert seen[0].headers["host"] == "127.0.0.1"
    assert json.loads(seen[1].content) == {
        "cik": None,
        "start_date": "2024-03-04",
        "end_date": "2024-03-04",
        "body": "x",
    }
    assert [r.method for r in seen[1:3]] == ["PUT", "DELETE"]
    assert status.spend_usd == Decimal("0.12") and status.enabled and status.listings_done is None


async def test_http_client_raises_on_a_problem_response() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(422, json={"title": "bad"})),
        base_url="http://x",
    )
    async with client:
        with pytest.raises(httpx.HTTPStatusError):
            await HttpAskApi(client).ask("?")


def test_parse_status_reads_backfill_progress() -> None:
    status = parse_status(
        {"ai": {"spend_usd": 1.5}, "backfill": {"listings_done": 98, "listings_total": 503}}
    )
    assert (status.spend_usd, status.enabled, status.listings_done) == (Decimal("1.5"), False, 98)


# --- the database adapter ------------------------------------------------------------


async def test_references_run_through_the_guard_as_dicts() -> None:
    executor = FakeExecutor(
        result([("symbol", "text"), ("pct_change", "numeric")], [("APA", Decimal("-84.8"))])
    )
    rows = await GuardedReferenceSource(executor).rows("SELECT symbol, pct_change FROM ai.daily_prices")
    assert rows == [{"symbol": "APA", "pct_change": Decimal("-84.8")}]
    assert "LIMIT 5001" in executor.queries[0]
    with pytest.raises(GuardError):
        await GuardedReferenceSource(executor).rows("DELETE FROM ai.notes")


# --- the cases file and the report -----------------------------------------------------


def test_the_cases_file_is_valid_and_covers_the_brief() -> None:
    cases = load_cases(DEFAULT_CASES_PATH)
    ids = {c.id for c in cases}
    assert 14 <= len(cases) <= 20
    assert {
        "covid_decline",
        "top10_market_cap_2020_2021",
        "note_prompt_injection",
        "out_of_scope_weather",
    } <= ids
    for c in cases:
        for reference in c.references.values():
            assert reference.sql.lstrip().upper().startswith(("SELECT", "WITH"))


def test_a_case_naming_an_unknown_reference_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown references"):
        case(references={})


async def test_scorecard_and_markdown_report_every_case() -> None:
    run, _ = runner(FakeApi(good_answer("Microsoft is largest.")))
    results = await run.run([case(id="wrong"), case(id="blocked", references={"top": {"sql": "SELECT 1"}})])
    info = RunInfo(date(2026, 9, 18), ANSWER_MODEL, JUDGE, Decimal("0.50"), STATUS, STATUS, stopped="")
    text = scorecard(results, info)
    assert "Pass rate: 0/1 (0%)" in text
    assert "wrong: fail" in text and "blocked: blocked" in text
    report = markdown(results, info)
    assert report.startswith("# Ask eval run, 2026-09-18")
    assert "| wrong | FAIL |" in report
    assert "> Microsoft is largest." in report
    assert totals(results).spend.cost_usd == Decimal("0.023")


def test_results_path_never_overwrites_an_earlier_run(tmp_path: Path) -> None:
    day = date(2026, 9, 18)
    first = results_path(tmp_path, day)
    assert first.name == "2026-09-18.md"
    first.write_text("x")
    assert results_path(tmp_path, day).name == "2026-09-18-2.md"
