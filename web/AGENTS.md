Repo-wide conventions live in `AGENTS.md` at the repo root, one level up (`CLAUDE.md` there is a symlink to it). Read it before making changes here.

This file exists so `next dev` (which runs from this directory) has somewhere to keep its managed agent-rules block below, without writing into the root file. Don't duplicate root conventions here.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
