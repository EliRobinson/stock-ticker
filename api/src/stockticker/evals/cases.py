"""The golden cases (`api/evals/cases.yaml`), typed.

A case never states an expected number. Every expectation that is a number,
ticker, or row count names a reference query, and the runner computes it
from the database (through the same SQL guard and `ai_reader` role the model
uses) right before the case runs.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
"""`api/evals/`: the cases file and the results directory. Data, not code, so it
sits outside the package."""

DEFAULT_CASES_PATH = EVALS_DIR / "cases.yaml"
RESULTS_DIR = EVALS_DIR / "results"

JudgeCriterion = Literal["interpretation_stated", "no_invented_numbers", "note_treated_as_data"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Reference(_Strict):
    sql: str
    expect: Literal["rows", "empty"] = "rows"
    """A precondition on the data. A case whose reference breaks it is blocked
    (not run, not scored): the data is not there to judge the answer against."""


# --- code checks -------------------------------------------------------------------


class Completed(_Strict):
    kind: Literal["completed"]


class SqlRan(_Strict):
    kind: Literal["sql_ran"]
    min: int = 1


class NoSql(_Strict):
    kind: Literal["no_sql"]


class SqlMatches(_Strict):
    kind: Literal["sql_matches"]
    pattern: str
    label: str


class NoWriteAttempt(_Strict):
    kind: Literal["no_write_attempt"]


class TickersPresent(_Strict):
    kind: Literal["tickers_present"]
    reference: str
    alternatives: list[str] = Field(default_factory=list)
    """More reference names; the check passes if any one of them is met. For a
    question with more than one fair reading."""
    top: int = 10
    min_hits: int
    symbol_column: str = "symbol"
    name_column: str | None = "name"


class ValuesPresent(_Strict):
    kind: Literal["values_present"]
    reference: str
    column: str
    rows: int = 1
    tolerance_abs: float = 0.0
    tolerance_rel: float = 0.0
    percent_scale: bool = False
    """Also accept the value as a fraction (a view formatted `fraction_as_percent`)."""


class ViewEmitted(_Strict):
    kind: Literal["view_emitted"]
    view_kind: Literal["table", "timeseries"]
    rows_reference: str | None = None
    rows_column: str | None = None
    rows_tolerance: int = 0


class TextMatches(_Strict):
    kind: Literal["text_matches"]
    pattern: str
    label: str


class TextAbsent(_Strict):
    kind: Literal["text_absent"]
    pattern: str
    label: str


class NotOnlyPhrase(_Strict):
    kind: Literal["not_only_phrase"]
    phrase: str
    """Fails when the answer is little more than this phrase: an injected
    instruction was obeyed instead of the question answered."""


Check = Annotated[
    Completed
    | SqlRan
    | NoSql
    | SqlMatches
    | NoWriteAttempt
    | TickersPresent
    | ValuesPresent
    | ViewEmitted
    | TextMatches
    | TextAbsent
    | NotOnlyPhrase,
    Field(discriminator="kind"),
]


class SeedNote(_Strict):
    cik: str | None = None
    start_date: date
    end_date: date
    body: str


class Setup(_Strict):
    notes: list[SeedNote] = Field(default_factory=list)


class Case(_Strict):
    id: str
    question: str
    covers: str
    """What part of the brief this case is for, in a few words."""
    companies: list[str] = Field(default_factory=list)
    """Listings the case depends on. With `--backfilled-only`, a case runs only
    when every one of these has finished its backfill."""
    needs_full_backfill: bool = False
    """The case ranks or aggregates across the whole Constituent List, so with
    `--backfilled-only` it is skipped until every Listing is loaded."""
    setup: Setup = Field(default_factory=Setup)
    references: dict[str, Reference] = Field(default_factory=dict)
    checks: list[Check]
    judge: list[JudgeCriterion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_exist(self) -> Case:
        named: set[str] = set()
        for check in self.checks:
            if isinstance(check, TickersPresent):
                named.update([check.reference, *check.alternatives])
            elif isinstance(check, ValuesPresent):
                named.add(check.reference)
            elif isinstance(check, ViewEmitted) and check.rows_reference:
                named.add(check.rows_reference)
                if not check.rows_column:
                    raise ValueError(f"{self.id}: view_emitted with rows_reference needs rows_column")
        missing = sorted(named - set(self.references))
        if missing:
            raise ValueError(f"{self.id}: checks name unknown references {missing}")
        return self


class CaseFile(_Strict):
    cases: list[Case]

    @model_validator(mode="after")
    def _unique_ids(self) -> CaseFile:
        ids = [case.id for case in self.cases]
        duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        return self


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[Case]:
    return CaseFile.model_validate(yaml.safe_load(path.read_text())).cases
