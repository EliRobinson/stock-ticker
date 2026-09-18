# Agent & AI Collaboration Guide

This file is the single source of truth for AI agents and humans working in this codebase. `CLAUDE.md` is a symlink to this file.

Domain terms (tickers, universes, whatever this app calls its own concepts) live in `CONTEXT.md` at the repo root - use its vocabulary rather than inventing your own. Architectural decisions are recorded in `docs/adr/`, one file per decision. The system's overall architecture lives in `docs/design/system-design.md`. Read what's relevant before making a structural change.

---

## Repo layout

This is a pnpm workspace, not a single app:

```
web/             # This Next.js app (see below)
api/             # Python 3.12 + FastAPI + a worker, managed with uv - added in an upcoming PR
docker-compose.yml # Postgres 17 + the services above - added in an upcoming PR
docs/
  adr/           # Architectural decision records
  design/        # System design docs, incl. system-design.md
CONTEXT.md       # Domain glossary - the vocabulary this app uses
```

`web/` never talks to Postgres directly. It calls the Python API for data; the API and worker own the database.

Repo-wide tooling - Husky, lint-staged, Commitizen, Commitlint, Prettier - lives in the root `package.json` and runs across the whole workspace. Each workspace package (currently just `web/`) owns its own dependencies and its own lint/type-check config. Run a `web` script from anywhere with `pnpm --filter web <script>`, or `cd web` first.

### Compose (for whoever adds `docker-compose.yml`)

The `web` service needs two named volumes, not one: one mounted at the repo root's `node_modules`, one at `web/node_modules`. A single shared volume lets the workspace's hoisted root `node_modules` and `web/node_modules` collide, and native binaries built on a macOS host end up in a Linux container. Don't turn on a polling watcher by default (no `CHOKIDAR_USEPOLLING`/`WATCHPACK_POLLING`) - it burns CPU on every host; only reach for it if native fs events turn out not to cross the bind mount.

---

## UI: shadcn/ui

UI in `web/` is built from **shadcn/ui** components (Tailwind v4, Radix primitives) plus:

- **TanStack Table** and **TanStack Virtual** for grids and large lists (tickers, screeners, historical data).
- **[lightweight-charts](https://tradingview.github.io/lightweight-charts/)** for price/time-series charts.
- **Vercel AI Elements** + `useChat` for any chat surface.

Add a component with the CLI, run from inside `web/`:

```bash
pnpm dlx shadcn@latest add <component>
```

Components land in `web/src/components/ui/` and are owned code from that point on - customize them freely, and don't overwrite them with a re-install; re-add instead.

### Rules

- Colors, radii, and shadows come from the shadcn theme variables in `globals.css` (`bg-background`, `text-muted-foreground`, `border-border`, etc.) or `var(--token)`. Never a hardcoded literal.
- Dark mode is the `.dark` class strategy. With `next-themes`, set `attribute="class"`.
- Use Tailwind utilities for layout and spacing directly on JSX. Avoid custom CSS files.
- Use `cn()` (from `@/lib/utils`) to merge conditional classes.
- Class order is enforced by `prettier-plugin-tailwindcss` - don't hand-sort.
- Missing a primitive shadcn doesn't ship? Compose it from what shadcn/Radix already gives you before reaching for another library.

### UI copy

Functional copy - errors, empty states, helper and hint text, toasts, labels, button text, tooltips, confirmations, validation - is chrome. **State the fact, then the consequence, then the action, and stop.** Never write:

- **Unverifiable frequency claims** - "almost always", "this rarely happens". You do not have that data.
- **Blame attribution** - "on their side", "check your connection". Say what is observable, not whose fault it might be.
- **Filler pacing** - "in a moment", "hang tight".
- **Unprompted reassurance or apology** - "don't worry", "we'll sort it out". Reassurance is allowed only when it answers a question the reader is actually asking, and then it is a fact: "You have not been charged."
- **Escalation paths nobody asked for** - "if it keeps happening, reply to…" belongs in a support surface, not a control.
- **Enthusiasm** - "Great news!", exclamation marks.

```
❌ You have not been charged. This is almost always a passing blip on their side,
   so try again in a moment. If it keeps happening, reply and we'll sort it out.
✅ You have not been charged. Try again.
```

**This governs chrome, not this product's editorial voice.** Marketing prose, conversational surfaces, and written deliverables are content - their voice is a deliberate design decision and this rule says nothing about them. Chrome follows this rule even on a surface that mixes the two. Read as an instruction to flatten the product's voice, it does more harm than the padding it removes.

If functional copy runs past two short sentences, it is explaining, reassuring, or selling - cut it back.

---

## Project Overview

The `web/` app is a **Next.js 16** frontend for an S&P 500 research app: App Router, TypeScript strict mode, Tailwind CSS v4, shadcn/ui, TanStack data libraries, and a full quality-gate toolchain. It calls the Python API (`api/`, arriving separately) for all data - it holds no database connection of its own, and the browser calls the API directly (see [Data fetching](#data-fetching-tanstack-query) below).

---

## Tech Stack

| Layer                  | Choice                                                                                                                           |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Framework              | Next.js 16 (App Router, Turbopack)                                                                                               |
| Language               | TypeScript 5 (strict, `@/*` path alias → `src/*`)                                                                                |
| Components & styling   | shadcn/ui (Tailwind v4, Radix primitives)                                                                                        |
| Tables & grids         | TanStack Table, TanStack Virtual                                                                                                 |
| Charts                 | lightweight-charts                                                                                                               |
| Chat                   | Vercel AI Elements + `useChat`                                                                                                   |
| Data fetching          | TanStack Query v5                                                                                                                |
| Forms                  | TanStack Form                                                                                                                    |
| Env validation         | `@t3-oss/env-nextjs` + Zod (`src/env.ts`)                                                                                        |
| Unit/integration tests | Vitest + React Testing Library                                                                                                   |
| E2E / functional tests | Playwright                                                                                                                       |
| Package manager        | pnpm (workspace root: this repo; `web` is one workspace package)                                                                 |
| Linting                | ESLint (Next.js flat config + `neostandard`), configured in `web/`                                                               |
| Formatting             | Prettier (`prettier-config-standard` + `prettier-plugin-tailwindcss`), configured and run at the repo root, across every package |
| Commits                | Commitizen + Commitlint (Conventional Commits), configured at the repo root                                                      |
| Dependency updates     | Renovate (auto-merge patch/minor + security)                                                                                     |

---

## Directory Structure (`web/`)

```
web/
  src/
    app/           # Next.js App Router pages and layouts
    components/
      ui/          # shadcn/ui components (added via CLI)
      providers.tsx # TanStack Query provider + devtools
    hooks/         # TanStack Query hooks, one file per resource
    lib/
      utils.ts     # cn() and shared utilities
      api.ts       # Typed API client - the only thing that calls fetch (arrives with #8)
      api-types.ts # Generated from the API's OpenAPI schema by `pnpm gen:api` (arrives with #8)
    env.ts         # Validated environment variables (@t3-oss/env-nextjs + Zod)
  tests/
    unit/          # Vitest + RTL unit & integration tests
  e2e/             # Playwright end-to-end tests
```

---

## Development Commands

Run from the repo root:

```bash
pnpm install                    # Install the whole workspace
pnpm --filter web dev           # Start dev server (Turbopack) on port 3000
pnpm --filter web build         # Production build
pnpm --filter web lint          # ESLint check
pnpm --filter web lint:fix      # ESLint auto-fix
pnpm format                     # Prettier write, whole repo
pnpm format:check               # Prettier check, whole repo
pnpm --filter web type-check    # tsc --noEmit
pnpm --filter web test          # Vitest (unit)
pnpm --filter web test:e2e      # Playwright (E2E)
pnpm commit                     # Commitizen interactive commit
```

`format`/`format:check` are repo-wide (root-owned Prettier, see [Tech Stack](#tech-stack)); everything else is `web`-scoped, and drops the `--filter web` prefix if you `cd web` first.

---

## Coding Conventions

### TypeScript

- Strict mode is on - no implicit `any`, no unchecked nulls.
- Use type imports: `import type { Foo } from "./foo"`.
- Prefer `interface` for object shapes that may be extended; `type` for unions/intersections.
- Path alias `@/` maps to `web/src/`.

### React & Next.js

- Default to **Server Components**. Add `"use client"` only when browser APIs or hooks are required.
- Server components never call the API. Inside `docker compose`, `127.0.0.1:8000` from the `web` container is not the API container, and the API's `TrustedHostMiddleware` rejects a request whose `Host` header is `api:8000`. The browser is the only caller, straight to `NEXT_PUBLIC_API_URL` - see [Data fetching](#data-fetching-tanstack-query).
- Keep Client Components as leaf nodes. Lift them out only when the boundary needs to move.
- Use `next/image` and `next/link` instead of `<img>` and `<a>`.

### Data fetching: TanStack Query

Every web ↔ API call goes through TanStack Query. No exceptions except `/chat` (below).

- No `fetch` in components. One typed client, `web/src/lib/api.ts`, built on the generated types in `web/src/lib/api-types.ts` (see [gen:api](#env-ports-and-the-generated-api-client)) - called only from query/mutation hooks in `web/src/hooks/`, one file per resource (`useMarket`, `useBars`, `useCompany`, `useEvents`, `useNotes`, `useStatus`).
- A query key factory per resource (`marketKeys`, `companyKeys`, `barsKeys`, `eventsKeys`, `notesKeys`, `statusKeys`).
- Caching: `bars` and `events` use a long `staleTime` (history rarely changes; invalidated after `bars_daily` updates). `market` and `status` poll with `refetchInterval` (10s while the market's open, 5min closed, paused while the tab is hidden). Range changes on the chart use `placeholderData: keepPreviousData` so it doesn't flash.
- Notes: `useMutation` with an optimistic update and rollback on error, then invalidate `notesKeys` - the chart markers read the same cache, so they update for free.
- Errors: a `problem+json` response becomes a typed `ApiError`. No retry on 4xx; 2 retries on network errors and 5xx.
- Company page: prefetch on Market row hover with `queryClient.prefetchQuery`.
- The one exception is the `/chat` stream, which `useChat` owns end to end. A `data-view` result renders straight from the stream and is never refetched.

### Error Handling

- Validate external input at system boundaries only (API routes, form submissions).
- Use Next.js `error.tsx` files for route-level error boundaries.
- Do not add defensive try/catch for code that cannot throw.

### Comments

- Write no comments by default. Only add one when the WHY is non-obvious: a hidden constraint, a workaround, or a subtle invariant.
- Do not comment what the code does - well-named identifiers handle that.

---

## Commit Standards

This project enforces **Conventional Commits**. All commits must match:

```
<type>(<optional scope>): <subject>

[optional body]

[optional footer(s)]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`

Use `pnpm commit` for the interactive Commitizen prompt. Direct `git commit` will be validated by the `commit-msg` Husky hook.

**Breaking changes:** add `!` after the type (`feat!:`) and a `BREAKING CHANGE:` footer.

---

## Pull requests

Every PR updates `README.md`: the brief-to-status table, and the "How this was built" artifacts table if the PR adds a process artifact (ADR, design doc, prompt, diagram).

---

## Visual Verification

- For any front-end change (component, page, layout, styling), take a screenshot of the affected UI before making the change and another after, using the Browser pane / preview tools.
- Attach both screenshots to the PR description (before/after) so reviewers can assess the UI/UX diff without pulling the branch.
- Skip this only when the change has no rendered visual effect (e.g. pure logic, types, non-UI server code).

---

## Testing Strategy

### Unit / integration (Vitest + RTL)

- Test files live in `web/tests/unit/` with the pattern `*.test.tsx`.
- Test user-visible behavior, not implementation details.
- Use `userEvent` over `fireEvent` for user interactions.
- Mock only at external boundaries (network, browser APIs). Do not mock internal modules.
- Coverage threshold: 70% branches/functions/lines.

### E2E (Playwright)

- Test files live in `web/e2e/` with the pattern `*.spec.ts`.
- Test critical user paths end-to-end against a running dev server.
- Use `page.getByRole()` and `page.getByText()` selectors (accessibility-first).
- Avoid `page.locator("css selector")` unless no semantic alternative exists.

---

## Git Hooks (Husky)

Hooks live at the repo root and run across the workspace.

The `pre-commit` hook runs `lint-staged`:

- `web/**/*.{ts,tsx,js,jsx,...}` → `web`'s ESLint fix
- Every `*.{ts,tsx,js,jsx,json,css,md,...}` in the repo, `web/` included → the root's Prettier

The `commit-msg` hook runs `commitlint` to enforce Conventional Commits.

The `pre-push` hook mirrors the fast CI jobs (`pnpm --filter web type-check`, `pnpm --filter web lint`, `pnpm format:check`, `pnpm --filter web test`) so a push that would fail CI fails locally first, before consuming a CI run. It intentionally skips `build` and `test:e2e` - those are slower and still run on the PR itself.

To skip hooks in an emergency: `git commit --no-verify` / `git push --no-verify` (discouraged - fix the underlying issue instead).

---

## Renovate Bot

Renovate runs automatically and:

- **Auto-merges** patch updates to production deps and minor+patch updates to devDependencies (when CI passes).
- **Auto-merges** security vulnerability fixes.
- **Requires manual review** for all major version bumps.
- Groups TanStack and Testing Library updates together.
- Pins GitHub Actions to digests.

---

## Env, ports, and the generated API client

Copy `.env.example` (repo root) to `.env` (repo root, git-ignored) for local development. There is one `.env` for the whole stack, not one per package: once `docker-compose.yml` lands, compose hands it to every service with `env_file`. `web/src/env.ts` (`@t3-oss/env-nextjs` + Zod) validates the vars `web` itself reads out of it - add a new one there, not just to `.env.example`, and prefix anything browser-exposed with `NEXT_PUBLIC_` in the `client` block.

- **Ports.** `web` on `127.0.0.1:3000`, the API on `127.0.0.1:8000`.
- **`NEXT_PUBLIC_API_URL`** defaults to `http://127.0.0.1:8000` in `src/env.ts`, so local `web` dev needs no `.env` at all unless the API runs somewhere else. The browser calls it directly - no Next.js rewrite, because a rewrite buffers the `/chat` SSE stream and has its own proxy timeout.
- **CSP.** `default-src 'self'; img-src 'self' data:; connect-src 'self' http://127.0.0.1:8000` - update the `connect-src` host if `NEXT_PUBLIC_API_URL` ever points elsewhere.
- **`pnpm gen:api`** (planned, tracked in [#8](https://github.com/EliRobinson/stock-ticker/issues/8)) will generate `web/src/lib/api-types.ts` from the API's OpenAPI schema; the generated file is committed, not built in CI. The script itself is a TODO until the API foundation lands.

---

## `api/` (Python)

Python 3.12, managed with `uv`. FastAPI for the REST + chat-stream service, Alembic for migrations, pytest for tests, ruff for lint/format. Full layout, the worker, and `docker-compose.yml` land with the API foundation PR (#3) - this section grows once that merges.

---

## Do Not

- Do not commit directly to `main`. Use feature branches and PRs.
- Do not use `any` without a `// eslint-disable-next-line` comment explaining why.
- Do not add `console.log` (only `console.warn`/`console.error` are permitted by ESLint).
- Do not bypass pre-commit hooks without a documented reason.
- Do not manually edit files in `web/src/components/ui/` to match a new shadcn version - re-add the component instead.
- Do not have `web/` open a direct database connection, or call the API from a server component. It's a browser-only, TanStack-Query-only call.
