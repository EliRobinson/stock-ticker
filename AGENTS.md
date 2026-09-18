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

Repo-wide tooling - Husky, lint-staged, Commitizen, Commitlint - lives in the root `package.json` and runs across the whole workspace. Each workspace package (currently just `web/`) owns its own dependencies, scripts, and lint/format/type-check config. Run a `web` script from anywhere with `pnpm --filter web <script>`, or `cd web` first.

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

The `web/` app is a **Next.js 16** frontend for an S&P 500 research app: App Router, TypeScript strict mode, Tailwind CSS v4, shadcn/ui, TanStack data libraries, and a full quality-gate toolchain. It calls the Python API (`api/`, arriving separately) for all data - it holds no database connection of its own.

---

## Tech Stack

| Layer                  | Choice                                                                      |
| ---------------------- | --------------------------------------------------------------------------- |
| Framework              | Next.js 16 (App Router, Turbopack)                                          |
| Language               | TypeScript 5 (strict, `@/*` path alias → `src/*`)                           |
| Components & styling   | shadcn/ui (Tailwind v4, Radix primitives)                                   |
| Tables & grids         | TanStack Table, TanStack Virtual                                            |
| Charts                 | lightweight-charts                                                          |
| Chat                   | Vercel AI Elements + `useChat`                                              |
| Data fetching          | TanStack Query v5                                                           |
| Forms                  | TanStack Form                                                               |
| Env validation         | `@t3-oss/env-nextjs` + Zod (`src/env.ts`)                                   |
| Unit/integration tests | Vitest + React Testing Library                                              |
| E2E / functional tests | Playwright                                                                  |
| Package manager        | pnpm (workspace root: this repo; `web` is one workspace package)            |
| Linting                | ESLint (Next.js flat config + `neostandard`)                                |
| Formatting             | Prettier (`prettier-config-standard` + `prettier-plugin-tailwindcss`)       |
| Commits                | Commitizen + Commitlint (Conventional Commits), configured at the repo root |
| Dependency updates     | Renovate (auto-merge patch/minor + security)                                |

---

## Directory Structure (`web/`)

```
web/
  src/
    app/           # Next.js App Router pages and layouts
    components/
      ui/          # shadcn/ui components (added via CLI)
      providers.tsx # TanStack Query provider + devtools
    hooks/         # Custom React hooks
    lib/
      utils.ts     # cn() and shared utilities
    server/
      actions/     # Server actions (Zod-validated input)
    types/         # Shared TypeScript types
    env.ts         # Validated environment variables (@t3-oss/env-nextjs + Zod)
  tests/
    unit/          # Vitest + RTL unit & integration tests
  e2e/             # Playwright end-to-end tests
```

---

## Development Commands

Run from the repo root (each proxies to the `web` workspace package):

```bash
pnpm install                    # Install the whole workspace
pnpm --filter web dev           # Start dev server (Turbopack) on a random free port
pnpm --filter web build         # Production build
pnpm --filter web lint          # ESLint check
pnpm --filter web lint:fix      # ESLint auto-fix
pnpm --filter web format        # Prettier write
pnpm --filter web format:check  # Prettier check
pnpm --filter web type-check    # tsc --noEmit
pnpm --filter web test          # Vitest (unit)
pnpm --filter web test:e2e      # Playwright (E2E)
pnpm commit                     # Commitizen interactive commit (repo root)
```

Or `cd web` first and drop the `--filter web` prefix.

---

## Coding Conventions

### TypeScript

- Strict mode is on - no implicit `any`, no unchecked nulls.
- Use type imports: `import type { Foo } from "./foo"`.
- Prefer `interface` for object shapes that may be extended; `type` for unions/intersections.
- Path alias `@/` maps to `web/src/`.

### React & Next.js

- Default to **Server Components**. Add `"use client"` only when browser APIs or hooks are required.
- Co-locate data-fetching with the server component that needs it.
- Keep Client Components as leaf nodes. Lift them out only when the boundary needs to move.
- Use `next/image` and `next/link` instead of `<img>` and `<a>`.

### TanStack Query

- Wrap queries in custom hooks inside `src/hooks/` (e.g. `useUsers.ts`).
- Export query key factories alongside hooks for cache invalidation.
- Use `suspense: true` + `<Suspense>` boundaries for loading states when possible.

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

- `web/**/*.{ts,tsx,js,jsx,...}` → `web`'s ESLint fix + Prettier
- `web/**/*.{json,css,md,...}` and root `*.{json,md,yml}` → Prettier

The `commit-msg` hook runs `commitlint` to enforce Conventional Commits.

The `pre-push` hook mirrors the fast CI jobs (`pnpm --filter web type-check`, `lint`, `format:check`, `test`) so a push that would fail CI fails locally first, before consuming a CI run. It intentionally skips `build` and `test:e2e` - those are slower and still run on the PR itself.

To skip hooks in an emergency: `git commit --no-verify` / `git push --no-verify` (discouraged - fix the underlying issue instead).

---

## Renovate Bot

Renovate runs automatically and:

- **Auto-merges** patch updates to production deps and minor+patch updates to devDependencies (when CI passes).
- **Auto-merges** security vulnerability fixes.
- **Requires manual review** for all major version bumps.
- Groups TanStack, Testing Library, and TypeScript ESLint updates together.
- Pins GitHub Actions to digests.

---

## Environment Variables

Copy `web/.env.example` to `web/.env.local` for local development. Never commit `.env.local` or any file containing secrets.

All env vars are declared and validated in `web/src/env.ts` (via `@t3-oss/env-nextjs` + Zod) - add new vars there, not just to `.env.example`. The build fails fast if a required var is missing or invalid, rather than failing at runtime in production. Prefix client-side variables with `NEXT_PUBLIC_` and list them in the `client` block of `src/env.ts`.

---

## Do Not

- Do not commit directly to `main`. Use feature branches and PRs.
- Do not use `any` without a `// eslint-disable-next-line` comment explaining why.
- Do not add `console.log` (only `console.warn`/`console.error` are permitted by ESLint).
- Do not bypass pre-commit hooks without a documented reason.
- Do not manually edit files in `web/src/components/ui/` to match a new shadcn version - re-add the component instead.
- Do not have `web/` open a direct database connection. It calls the Python API.

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.
