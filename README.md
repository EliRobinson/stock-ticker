# stock-ticker

An S&P 500 research app.

This repo is a pnpm workspace. `web/` is the Next.js 16 frontend (App
Router, TypeScript strict mode, Tailwind CSS v4, shadcn/ui, TanStack).
`api/` (Python FastAPI + a worker, Postgres 17, docker-compose) is
arriving in an upcoming PR - `web/` never talks to the database directly,
only to the API.

See [`AGENTS.md`](AGENTS.md) for full conventions (stack, coding rules,
testing strategy, commit standards), [`CONTEXT.md`](CONTEXT.md) for the
domain glossary once it lands, and [`docs/adr/`](docs/adr) for
architectural decisions.

## Getting started

```bash
nvm use              # or: node --version should match .nvmrc
pnpm install          # installs the whole workspace
cp web/.env.example web/.env.local
pnpm --filter web dev
```

The dev server binds to a random free port and prints it, e.g.
`Local: http://localhost:63205`.

## Common commands

Run from the repo root; each proxies to the `web` workspace package (or
`cd web` first and drop the `--filter web` prefix):

```bash
pnpm --filter web build         # production build
pnpm --filter web lint          # ESLint
pnpm --filter web format:check  # Prettier
pnpm --filter web type-check    # tsc --noEmit
pnpm --filter web test          # Vitest
pnpm --filter web test:e2e      # Playwright
pnpm commit                     # Commitizen guided commit
```

## CI

GitHub Actions runs on every push and pull request to `main`. See
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) - `quality`
(type-check, lint, format), `unit` (Vitest with coverage), and `e2e`
(Playwright against a production build).
