"""The scorecard: a plain-text table for the terminal and a Markdown report
for `api/evals/results/<date>.md`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from stockticker.evals.runner import ApiStatus, CaseResult, Outcome, Spend

ANSWER_EXCERPT_CHARS = 900
SCORED = (Outcome.PASS, Outcome.FAIL, Outcome.ERROR)


@dataclass(frozen=True)
class RunInfo:
    day: date
    answer_model: str
    judge_model: str | None
    budget_usd: Decimal
    before: ApiStatus
    after: ApiStatus
    stopped: str = ""


@dataclass(frozen=True)
class Totals:
    scored: int
    passed: int
    spend: Spend
    answer_spend: Spend
    judge_spend: Spend

    @property
    def pass_rate(self) -> str:
        return f"{self.passed}/{self.scored} ({self.passed / self.scored:.0%})" if self.scored else "0/0"


def totals(results: Sequence[CaseResult]) -> Totals:
    scored = [r for r in results if r.outcome in SCORED]
    answer = sum((r.answer_spend for r in results), Spend())
    judge = sum((r.judge_spend for r in results), Spend())
    return Totals(
        scored=len(scored),
        passed=sum(r.outcome is Outcome.PASS for r in scored),
        spend=answer + judge,
        answer_spend=answer,
        judge_spend=judge,
    )


def _row(result: CaseResult) -> list[str]:
    checks = f"{sum(c.passed for c in result.checks)}/{len(result.checks)}" if result.checks else "-"
    judged = f"{sum(v.passed for v in result.verdicts)}/{len(result.verdicts)}" if result.verdicts else "-"
    steps = str(result.transcript.steps) if result.transcript else "-"
    spend = result.spend
    return [
        result.case.id,
        result.outcome.value.upper(),
        checks,
        judged,
        steps,
        f"{spend.input_tokens:,}" if spend.calls else "-",
        f"{spend.output_tokens:,}" if spend.calls else "-",
        f"${spend.cost_usd:.4f}" if spend.calls else "-",
    ]


HEADERS = ["case", "result", "checks", "judge", "steps", "tokens in", "tokens out", "cost"]


def scorecard(results: Sequence[CaseResult], info: RunInfo) -> str:
    rows = [HEADERS, *(_row(r) for r in results)]
    widths = [max(len(row[i]) for row in rows) for i in range(len(HEADERS))]
    lines = ["  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)) for row in rows]
    lines.insert(1, "  ".join("-" * width for width in widths))
    t = totals(results)
    lines += [
        "",
        f"Pass rate: {t.pass_rate} scored cases",
        f"Cost: ${t.spend.cost_usd:.4f} (answers ${t.answer_spend.cost_usd:.4f}, "
        f"judge ${t.judge_spend.cost_usd:.4f}); budget ${info.budget_usd:.2f}",
        f"Tokens: {t.spend.input_tokens:,} in, {t.spend.output_tokens:,} out",
        f"Ledger (/api/v1/status): ${info.before.spend_usd:.4f} before, ${info.after.spend_usd:.4f} after",
    ]
    for result in results:
        if result.outcome in (Outcome.FAIL, Outcome.ERROR):
            lines.append(f"\n{result.case.id}: {result.outcome.value}")
            lines += [f"  - {failure}" for failure in result.failures]
            if result.reason:
                lines.append(f"  - {result.reason}")
        elif result.outcome in (Outcome.BLOCKED, Outcome.SKIPPED):
            lines.append(f"\n{result.case.id}: {result.outcome.value}: {result.reason}")
    return "\n".join(lines)


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def markdown(results: Sequence[CaseResult], info: RunInfo) -> str:
    t = totals(results)
    backfill = (
        f"{info.before.listings_done}/{info.before.listings_total}"
        if info.before.listings_done is not None
        else "unknown"
    )
    out = [
        f"# Ask eval run, {info.day.isoformat()}",
        "",
        f"- Answer model: `{info.answer_model}`. Judge model: `{info.judge_model or 'off'}`.",
        f"- Pass rate: **{t.pass_rate}** of scored cases. Blocked and skipped cases are not scored.",
        f"- Cost: **${t.spend.cost_usd:.4f}** (answers ${t.answer_spend.cost_usd:.4f}, judge "
        f"${t.judge_spend.cost_usd:.4f}) against a ${info.budget_usd:.2f} budget.",
        f"- Tokens: {t.spend.input_tokens:,} in, {t.spend.output_tokens:,} out.",
        f"- Spend ledger (`/api/v1/status`): ${info.before.spend_usd:.4f} before, "
        f"${info.after.spend_usd:.4f} after, limit ${info.after.limit_usd:.2f}.",
        f"- Backfill when the run started: {backfill} Listings done.",
    ]
    if info.stopped:
        out.append(f"- Stopped early: {info.stopped}.")
    out += [
        "",
        "## Scorecard",
        "",
        "| " + " | ".join(HEADERS) + " |",
        "|" + "|".join("---" for _ in HEADERS) + "|",
    ]
    out += ["| " + " | ".join(_md_cell(cell) for cell in _row(r)) + " |" for r in results]
    out += ["", "## Cases", ""]
    for result in results:
        out += _case_section(result)
    return "\n".join(out).rstrip() + "\n"


def _case_section(result: CaseResult) -> list[str]:
    case = result.case
    out = [f"### {case.id}: {result.outcome.value}", "", f"> {case.question}", "", f"Covers: {case.covers}."]
    if result.reason:
        out += ["", f"Reason: {result.reason}"]
    if result.checks or result.verdicts:
        out.append("")
        out += [
            f"- {'PASS' if c.passed else 'FAIL'} {c.name}{': ' + c.detail if c.detail else ''}"
            for c in result.checks
        ]
        out += [
            f"- {'PASS' if v.passed else 'FAIL'} judge {v.criterion}: {v.reason}" for v in result.verdicts
        ]
    transcript = result.transcript
    if transcript is not None:
        sql = [call.sql for call in transcript.sql_calls if call.sql]
        if sql:
            out += ["", "<details><summary>SQL the model ran</summary>", "", "```sql"]
            out += [statement.strip() + ";" for statement in sql]
            out += ["```", "", "</details>"]
        text = transcript.text or "(no text)"
        if len(text) > ANSWER_EXCERPT_CHARS:
            text = text[:ANSWER_EXCERPT_CHARS] + " [...]"
        out += ["", "Answer:", ""]
        out += ["> " + line if line else ">" for line in text.splitlines()]
        if transcript.error:
            out += ["", f"Stream error: {transcript.error}"]
    out.append("")
    return out


def results_path(directory: Path, day: date) -> Path:
    """`<date>.md`, or `<date>-2.md` and up when a run that day already wrote one."""
    path = directory / f"{day.isoformat()}.md"
    run = 2
    while path.exists():
        path = directory / f"{day.isoformat()}-{run}.md"
        run += 1
    return path
