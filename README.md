# stock-ticker

An S&P 500 research tool: live Quotes, charts and tables of price history, dated Notes tied to companies and events, and an AI that answers questions with tables and charts of its own.

## Brief to status

The [design brief](docs/design/brief.md) sets four requirements. This table tracks how each is met and where the work stands.

| Requirement                                | How it's met                                                                                                                                                                                                              | Status                                                                                                                                                                                      |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fresh data: live Quotes and daily history  | A Python worker polls Alpaca for Quotes and backfills Daily Bars, and computes Market Cap from SEC EDGAR share counts. FastAPI serves it all read-only.                                                                   | Planned: [#3](https://github.com/EliRobinson/stock-ticker/issues/3), [#4](https://github.com/EliRobinson/stock-ticker/issues/4), [#5](https://github.com/EliRobinson/stock-ticker/issues/5) |
| Tables and charts, with zoom, filter, sort | TanStack Table and TanStack Virtual drive the Market table; lightweight-charts drives the price chart, with range presets and a custom range picker.                                                                      | Planned: [#8](https://github.com/EliRobinson/stock-ticker/issues/8), [#9](https://github.com/EliRobinson/stock-ticker/issues/9)                                                             |
| Notes tied to dates and companies          | A Notes CRUD endpoint on the API; the web app renders Notes as chart markers and as a filterable list, last write wins.                                                                                                   | Planned: [#6](https://github.com/EliRobinson/stock-ticker/issues/6), [#9](https://github.com/EliRobinson/stock-ticker/issues/9)                                                             |
| AI that answers with tables and charts     | A Python tool loop runs Claude over guarded, read-only SQL and streams the AI SDK UI message protocol. The web app renders the resulting `data-view` parts with the same table and chart components used everywhere else. | Planned: [#7](https://github.com/EliRobinson/stock-ticker/issues/7), [#8](https://github.com/EliRobinson/stock-ticker/issues/8)                                                             |

[#2](https://github.com/EliRobinson/stock-ticker/issues/2) (this PR) sets up the repo the rest of the work builds on. [#10](https://github.com/EliRobinson/stock-ticker/issues/10) closes out with the final README pass and the submission answers below.

## Run it locally

**Prerequisites:**

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Free Alpaca paper-trading API keys: [alpaca.markets](https://alpaca.markets)
- An Anthropic API key
- A `SEC_USER_AGENT` of the form `"Name email"` (SEC EDGAR requires this on every request)

**Steps:**

```bash
cp .env.example .env
# fill in .env: Alpaca keys, ANTHROPIC_API_KEY, SEC_USER_AGENT
docker compose up
```

Then open [http://127.0.0.1:3000](http://127.0.0.1:3000). The first start backfills price history in the background; the header shows its progress while it runs.

The Docker stack (`docker-compose.yml`, the API, the worker) lands with [#3](https://github.com/EliRobinson/stock-ticker/issues/3). Until then, this repo is `web/` on its own:

```bash
pnpm install
pnpm --filter web dev
```

**Tests:** `pnpm --filter web test`. The API's test suite (pytest) arrives with [#3](https://github.com/EliRobinson/stock-ticker/issues/3).

## Architecture at a glance

Full detail: [docs/design/system-design.md](docs/design/system-design.md). Diagrams: `docs/design/diagrams.md` (arriving in PR #11).

Postgres holds Listings, Companies, Daily Bars, Notes, and Events. A Python worker ingests Alpaca and SEC EDGAR data on a schedule, one job per advisory lock. FastAPI serves a read-only REST API plus a chat stream, and runs a Claude tool loop over guarded SQL for that chat. Next.js (`web/`) calls the API directly from the browser, no server-side proxy, and renders the result with TanStack Table, lightweight-charts, and AI Elements. Claude is the model behind Ask, restricted to read-only views and an allow-listed SQL surface.

## How this was built

| Artifact                                   | What it is                                                                                                                                                                                                      | Link                                                         |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `CONTEXT.md`                               | Domain glossary: the vocabulary this app and its code use                                                                                                                                                       | [CONTEXT.md](CONTEXT.md)                                     |
| `docs/adr/`                                | Architectural decision records: 0001 Alpaca and SEC EDGAR as free data sources, 0002 Local Postgres over SQLite, 0003 AI loop runs in Python speaking the AI SDK protocol, 0004 Drop the personal design system | [docs/adr/](docs/adr)                                        |
| `docs/design/system-design.md`             | The full system design, reviewed by parallel critic agents across two rounds                                                                                                                                    | [docs/design/system-design.md](docs/design/system-design.md) |
| `docs/design/diagrams.md`                  | Mermaid architecture diagrams                                                                                                                                                                                   | Arriving in PR #11                                           |
| `docs/design/brief.md`                     | The Claude Design UI brief, the prompt the four screens are built from                                                                                                                                          | [docs/design/brief.md](docs/design/brief.md)                 |
| GitHub issues and labels                   | The work tracker: `status:*`, `area:*`, `model:*`, `needs-eli`                                                                                                                                                  | [Issues](https://github.com/EliRobinson/stock-ticker/issues) |
| Git worktrees, parallel Claude Code agents | One model picked per task: Opus 5 for design critique, the AI loop, Market Cap math, and reviews; Sonnet 5 for most building; Haiku 4.5 for docs                                                                | -                                                            |
| A code-quality review before every PR      | A thermonuclear review, then cross-critique by a second agent                                                                                                                                                   | -                                                            |
| `AGENTS.md` / `CLAUDE.md`                  | The agent guide                                                                                                                                                                                                 | [AGENTS.md](AGENTS.md)                                       |

## Tech stack

| Layer    | Choice                                                                                                                                                                         |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Frontend | Next.js 16, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query/Table/Virtual, lightweight-charts, AI Elements                                                              |
| Backend  | Python 3.12, FastAPI, uv, Alembic (planned, [#3](https://github.com/EliRobinson/stock-ticker/issues/3))                                                                        |
| Data     | Postgres 17, a worker on Alpaca and SEC EDGAR (planned, [#3](https://github.com/EliRobinson/stock-ticker/issues/3)-[#5](https://github.com/EliRobinson/stock-ticker/issues/5)) |
| AI       | Claude, a Python tool loop over guarded SQL, the AI SDK protocol (planned, [#7](https://github.com/EliRobinson/stock-ticker/issues/7))                                         |
| Tests    | Vitest, React Testing Library, Playwright; pytest (planned, [#3](https://github.com/EliRobinson/stock-ticker/issues/3))                                                        |
| Tooling  | pnpm workspace, ESLint, Prettier, Husky, Commitlint, Renovate, Docker Compose (planned, [#3](https://github.com/EliRobinson/stock-ticker/issues/3))                            |

## Known limits

- Live prices come from Alpaca's free IEX feed, not the full consolidated tape.
- The Constituent List is today's S&P 500 membership only; companies that left the index are absent (survivorship bias).
- Multi-class Market Cap uses a seeded per-issuer rule, not real per-class share counts, because free sources do not publish them.
- Local, single user, no authentication.

## Submission answers

Written at the end ([#10](https://github.com/EliRobinson/stock-ticker/issues/10)).
