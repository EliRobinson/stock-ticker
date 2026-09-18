# Handoff

This file is for whoever continues this build, whether a human or an agent (Cursor, Claude Code, or another tool). Read it first, then `AGENTS.md`, `CONTEXT.md`, and `docs/design/system-design.md`.

Last updated: 2026-09-18.

## 1. State of the build

### Merged to `main`

| PR                          | What                                                                                                  |
| --------------------------- | ----------------------------------------------------------------------------------------------------- |
| #1, #11, #14, #15, #18, #19 | Domain glossary, ADRs, system design, Mermaid diagrams (C4 levels 1 to 4), UI brief, spec updates     |
| #12                         | Personal design system removed. Next.js app moved into `web/`                                         |
| #13                         | CI checks moved into git hooks. GitHub Actions only runs a notice job                                 |
| #16, #17, #28               | `AGENTS.md`: the review gate, agent collaboration rules, the copywriting rule, the DRY critic         |
| #33                         | API foundation: FastAPI, schema, roles, `ai` views, the job framework, compose                        |
| #30                         | Ingest: constituents, EDGAR share counts and filings, the point-in-time Market Cap rebuild, gap check |
| #25                         | Read API and Notes                                                                                    |
| #21                         | AI chat: guarded SQL tools, the AI SDK stream protocol, the $5 spend cap                              |
| #22                         | Web data layer: TanStack Query hooks, typed client, formatters, chart and table logic                 |
| #34                         | Integration fix after #21 and #25 (openapi.json, stub test)                                           |

On `main`, 788 API tests and 173 web tests pass.

### In flight

Each branch lives on origin. Check them with `git fetch && gh pr list`.

| Branch              | Issue / PR  | State                                                                                                                                                                              | Next step                                                                                                                           |
| ------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| (merged)            | #4 / PR #27 | Merged. The API suite on `main` passes (847 tests).                                                                                                                                | None.                                                                                                                               |
| `feat/web-screens`  | #9          | The four-reviewer gate is done. The builder is fixing the findings (21 FIX items plus DRY; list below). Security items 1 and 2 (raw HTML, CSP) are done. It is rebased onto `main` | Finish the fixes, copy `api/openapi.json` to `web/openapi/`, run `pnpm gen:api`, open the PR with `--base main`, then Eli labels it |
| `fix/api-followups` | #32, #24    | A builder just started                                                                                                                                                             | Push, run the four-reviewer gate, open the PR                                                                                       |
| `fix/ai-followups`  | #20         | A builder just started                                                                                                                                                             | Push, run the four-reviewer gate, open the PR                                                                                       |

### Not started

- **#26 and #29:** ingest cleanups. They touch the same files as #27, so start them after #27 merges.
- **#23:** AI eval suite. It needs #27 merged and a real backfill in the local DB. See section 5.
- **#31:** ViewSpec Zod schema generated from OpenAPI. This is web work; give it to whoever owns `web/src/lib`.
- **#10:** final README and the submission answers. Do this last.

### Remaining screens (#9) findings

If the #9 builder stops, this is the list to finish. Items 1 and 2 are already done.

1. Raw HTML renders in markdown. Streamdown applies rehype-raw. Done.
2. CSP header missing. Done.
3. A failed Company request shows the skeleton forever. Branch on the error first; a 404 calls `notFound()`; zero bars gets its own empty state.
4. The chart is torn down on every toggle, refetch, or theme change. Create it once per theme and update data with `setData`.
5. Only the first page of Notes and Events is used. Fetch all pages.
6. The Ask chat is lost when the panel closes below 900px. Share one `Chat` from the shell.
7. The `data-view` payload is not validated. Use `parseViewSpec`, sort and dedupe x, and give each view its own error boundary.
8. Fast typing in Market search drops characters.
9. A failed Note save loses the text. Keep the dialog open until the save succeeds.
10. Adding a Note from the keyboard on the Company screen locks the dates. Lock only the Company.
11. At 400px the sector filter is invisible.
12. "Outside chart range" uses the visible preset. Use the loaded bars instead.
13. Stop during a tool call leaves a spinner.
14. `useRouter` is used inside the presentational shell, and `presetOptions` is not memoized.
15. `chart-data` should emit `PlacedMarker` directly.
16. `/dev/states` must be excluded at build time.
17. Accent-fill contrast fails AA, and input borders are below 3:1.
18. The price label overlaps an axis label on the chart.
19. The copy says "Symbol". Use "Ticker".
20. README: fix the Claude Design attribution.
21. Tests for items 3, 5 to 9, plus an axe-core Playwright spec.

DRY items: delete the rename-only format shims; use `ui/table`; add `useSaveNote`, `lib/company.ts` (with a single `primaryListing`), one `ClampedText`, `QuoteCell` with a size prop, `shared/copy.ts`, and `lib/routes.ts`; keep each constant in one place; delete the redundant `error.tsx` files.

Decisions already made: Company range, mode, and tab, plus the Notes filters, go in the URL. Adopt shadcn `Alert`, `Skeleton`, `Tabs`, and `Table`. Backfill states read `backfill_completed_at`. Show the approximate-Market-Cap marker on Market too.

## 2. How to run it

```bash
cp .env.example .env    # then fill ALPACA_KEY_ID, ALPACA_SECRET_KEY, SEC_USER_AGENT, ANTHROPIC_API_KEY
pnpm install --frozen-lockfile
./scripts/dev.sh
```

Then open http://127.0.0.1:3000.

- Eli's `.env` already has all keys, plus 3 generated `POSTGRES_*_PASSWORD` values. Never print or copy `.env`.
- The API has an Anthropic spend cap: `AI_SPEND_LIMIT_USD=5`. The Anthropic Console has a $5 limit too. Do not run the evals or the live AI more than needed.
- API tests: create/migrate `stockticker_test`, then run pytest against it (never the app DB):

```bash
docker compose run --rm --no-deps --entrypoint "" migrate \
  sh -c "uv run --no-sync python scripts/ensure_test_database.py"
docker compose run --rm --no-deps --entrypoint "" \
  -e POSTGRES_DB=stockticker_test -e POSTGRES_TEST_DB=stockticker_test api \
  sh -c "REQUIRE_DB=1 uv run --no-sync pytest tests -q"
```

- Web tests: `pnpm --filter web test`. E2E: `RUN_E2E=1 git push`, or `pnpm --filter web test:e2e`.
- The pre-push hook is the CI gate. It runs web type-check, lint, format, tests, and build, and, when `api/` changed, api ruff, mypy, and pytest. Never use `--no-verify`.
- Hooks path gotcha: `pnpm install` inside a git worktree rewrites `core.hooksPath` to a relative path, and then worktrees without their own install run no hooks. After installing, set it back with `git config core.hooksPath "$PWD/.husky/_"` from the main checkout.

## 3. Rules of the road

- **Branches and PRs.** One branch per issue. Never commit to `main`. Use Conventional Commits, and end every message with the `Co-Authored-By` line from `AGENTS.md`.
- **Merging.** A PR with Eli's label `aareviewed:merge` may be merged. The repo only allows rebase merges: `gh pr merge <n> --rebase --delete-branch`. Never merge a PR that lacks the label.
- **Rebase.** After fixes, every PR rebases onto the latest `main`, runs the full hook, pushes with `--force-with-lease`, and confirms `gh pr view <n> --json mergeable` reports MERGEABLE.
  - After a stacked base merges, use `git rebase --onto origin/main <old base tip> <branch>` to drop the rewritten commits.
  - After merging two PRs that were tested on different bases, run the full API test suite on `main` before anything else merges. #34 exists because this was skipped once.
- **README.** Every PR updates the README status table, plus the "How this was built" table if it adds a process artifact.
- **Copy.** Every user-facing string goes through the `copywriting` skill (`.claude/skills` or a Cursor equivalent) and the UI copy rules in `AGENTS.md`. Use the glossary terms in `CONTEXT.md`.
- **Ownership.** Never edit a file another in-flight branch owns. Ask the owner, or leave a note on its issue.
- **Decisions.** Record them on the GitHub issue. The labels are `status:*`, `area:*`, `model:*`, and `needs-eli`.

## 4. The agent patterns (use these in Cursor too)

The build uses one coordinator and many parallel workers. Each worker gets its own git worktree and branch. Workers talk to each other about contracts, and critics review before any PR opens.

In Cursor, run each role as its own Background Agent, or as a separate chat/agent tab, on its own branch. The coordinator (you, or one agent) assigns work, collects critic output, and relays combined findings to the builder. If agents cannot message each other, use GitHub issue comments as the channel.

### Model choice

| Role                                                                                       | Model                                                                                |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Thermonuclear review, final audit                                                          | The strongest reasoning model available (Fable 5.1, or Opus if Fable is unavailable) |
| Correctness critic, DRY critic, hard builds (Market Cap math, AI loop, SQL guard, screens) | Opus 5                                                                               |
| Most building, the spec/security/copy critic, diagrams, docs                               | Sonnet 5                                                                             |
| Purely mechanical edits                                                                    | Haiku 4.5                                                                            |

### Builder prompt template

```
You own GitHub issue #<N> in EliRobinson/stock-ticker: <title>. Run `gh issue view <N> --comments` and follow every comment.
Setup: `git fetch origin`; create branch `<branch>` from `origin/main`; `pnpm install --frozen-lockfile`. Read AGENTS.md, CONTEXT.md, and docs/design/system-design.md §<sections>. Comment on the issue when you start, and set `status:in-progress`.
Scope: <exact list>. Files you own: <paths>. Do not edit other paths; ask their owner instead.
Tests: <what must be tested>. Mock only at external boundaries.
Finish: Conventional Commits with the Co-Authored-By line. Run the full pre-push hook with no bypass. Push. Do NOT open a PR; report to the coordinator for the review gate.
```

### Review gate: four critics, run in parallel and read-only

Pin each critic to a commit SHA, so it reviews exactly what was pushed. `<base>` is `origin/main` unless the branch is stacked.

**1. Thermonuclear (strongest model)**

```
Run a thermonuclear code-quality review. Read-only: do not edit, commit, or push. If a `code-quality-review` skill exists, follow it. Otherwise, hunt for bad abstractions, giant files and functions, spaghetti conditionals, leaky boundaries, and structural rewrites worth doing now.
Target: branch `<branch>` at `<sha>` (issue #<N>). Review `git diff <base>...<sha>`. Spec: docs/design/system-design.md §<x>, AGENTS.md, `gh issue view <N> --comments`.
Weigh interface quality heavily if other work builds on this.
Output (under 600 words): findings ranked most severe first, each with file:line, the defect, the concrete failure, and the fix. Tag each FIX, FIX-LATER, or ELI (needs a human call; say why).
```

**2. Correctness critic (Opus)**

```
You are the correctness critic for `<branch>` at `<sha>` (issue #<N>). Read-only. Review `git diff <base>...<sha>`. Spec: <sections>.
Try to make it produce wrong results, lose data, crash, or leak: edge cases, error paths, concurrency, timezones and Trading Days, idempotency, security boundaries. Write probes and run them in a throwaway worktree or DB when possible, then remove them.
For every area, ask whether the tests would catch a regression.
Output (under 700 words): findings ranked by severity, each with a concrete scenario and a fix, tagged FIX, FIX-LATER, or ELI.
```

**3. Spec, security, and copy critic (Sonnet)**

```
You are the spec, security, and copy critic for `<branch>` at `<sha>` (issue #<N>). Read-only.
1) Spec conformance against docs/design/system-design.md, CONTEXT.md (glossary words, including its "Avoid" lists), and the issue comments. Flag every deviation.
2) Security: secrets, injection, SSRF, XSS (no raw HTML, no remote images, https-only links), ports bound to 127.0.0.1, the AI role and guard.
3) Copy: run every user-facing string through the `copywriting` skill and the AGENTS.md UI copy rules (fact, then consequence, then action; no AI-isms). Quote each bad string with its replacement.
4) README status row updated.
Output (under 500 words): findings, each with file:line, the problem, and the fix, tagged FIX, FIX-LATER, or ELI.
```

**4. DRY critic (Opus)**

```
You are the DRY critic for `<branch>` at `<sha>` (issue #<N>). Read-only. Review `git diff <base>...<sha>`, and read whole files with `git show <sha>:<path>`.
Hunt for: repeated literals and constants; near-duplicate functions; parallel structures that should be one parametrized thing; hand-written types that duplicate generated ones (web/src/lib/api-types.ts, api/openapi.json); the same rule written in two places, including across branches and main; copied test setup.
Also name look-alikes to LEAVE alone, because they change for different reasons.
Output (under 500 words): findings ranked by impact, each with every file:line, what is duplicated, and the single named home it should move to. Tag each FIX, FIX-LATER, or LEAVE.
```

### After the critics

The coordinator merges the four outputs into one message for the builder:

- the FIX list;
- the FIX-LATER list, to do now if quick, otherwise file one issue;
- a decision on each ELI item (escalate to Eli only if it truly needs him);
- the LEAVE list.

The builder then:

1. Checks each finding against the code, fixes the valid ones, and pushes back with evidence on the rest.
2. Rebases onto `main` and runs the full hook.
3. Opens the PR with a **Review** section that marks every finding as fixed, declined (with the reason), or filed (with the issue link).
4. Waits for Eli's label, then merges.

Docs-only PRs skip the gate.

## 5. What's left to finish the brief

1. **Merge #27 (Alpaca).** Then run the full API suite on `main`.
2. **Finish #9 (screens).** Run through the gate fixes above, then open the PR and merge it.
3. **Load real data.** Run `./scripts/dev.sh`. The worker's startup chain runs: constituents, then calendar, then backfill, EDGAR, and corporate actions together, then the market cap rebuild. The full backfill is roughly 1.1M bars. Watch `/api/v1/status` for backfill progress. Check that `/market` and a Company chart show real prices, and that NVDA's 2024 split is adjusted.
4. **Build #23 (evals).** Use about 15 golden questions, including the brief's COVID-decline question and the top-10-by-market-cap question. Checks are code-based, with an LLM judge for wording only. Keep each run under $0.50, and put the scorecard in the README.
5. **Merge #32/#24 and #20** after their gates. Then do #26/#29 (ingest cleanups) and #31.
6. **Refresh the diagrams.** Update the Level 4 code diagrams in `docs/design/diagrams.md` for the AI and screens code, which were drawn from the spec.
7. **Write the final README (#10).** It needs run steps, a feature walkthrough with screenshots, the "How this was built" table (including this handoff and the agent patterns), known limits, and the three submission answers (process and trade-offs; happy or not and why; what to do differently). Run the text through the copywriting skill.
8. **Record the demo video**, which Eli does.

## 6. Known risks

- **Worktree cleanup.** A worker's worktree can be removed when the worker finishes. Unpushed commits survive on the local branch ref (`git branch -v`). Push checkpoints often.
- **Stacked PRs.** When a base PR is rebase-merged, its commit SHAs change, and every stacked PR shows a conflict. Use `git rebase --onto` as described above.
- **Spend.** The $5 Anthropic cap covers everything: the smoke tests, the evals, and demo use. `/api/v1/status` shows `ai.spend_usd`.
