# System Design Diagrams

Mermaid renderings of the design in [system-design.md](system-design.md), using the terms defined in [CONTEXT.md](../../CONTEXT.md).

## 1. System context (C4 Level 1)

Look at who the app talks to and why: the user drives it, and it reaches out to four external systems. This is the widest zoom; nothing about compose services or Postgres roles appears here.

```mermaid
flowchart TD
    user(["User"])
    app["Stock Ticker (this app)"]
    alpaca["Alpaca"]
    edgar["SEC EDGAR"]
    wiki["Wikipedia"]
    anthropic["Anthropic"]

    user -->|"views Market, Company, and Notes; asks questions"| app
    app -->|"Quotes, Daily Bars, calendar, corporate actions"| alpaca
    app -->|"shares outstanding, filings"| edgar
    app -->|"S&P 500 constituent table"| wiki
    app -->|"natural-language answers"| anthropic
```

## 2. Containers (C4 Level 2)

One level in from the context diagram: the four compose services inside the loopback trust boundary, the Postgres roles on each edge into `db`, the `ai` schema sitting between `ai_reader` and the tables, the `migrate` service that both `api` and `worker` wait on, and the one edge where data (Notes and query rows) leaves the machine for Anthropic.

```mermaid
flowchart LR
    subgraph external["External systems"]
        alpaca["Alpaca"]
        edgar["SEC EDGAR"]
        wiki["Wikipedia"]
        anthropic["Anthropic"]
    end

    subgraph compose["Docker Compose: loopback trust boundary, every port bound to 127.0.0.1, nothing reachable from outside the machine"]
        migrate["migrate (one-shot: alembic upgrade head)"]
        worker["worker (APScheduler, no published port)"]
        subgraph dbbox["db: Postgres 17 (not published)"]
            tables[("domain tables (app_owner)")]
            aiviews["ai schema: views + ai.returns_between + ai.today_ny (SECURITY DEFINER)"]
        end
        api["api (FastAPI, 127.0.0.1:8000)"]
        web["web (Next.js 16, 127.0.0.1:3000)"]
    end

    browser(["Browser"])

    alpaca --> worker
    edgar --> worker
    wiki --> worker

    migrate -->|"must complete (service_completed_successfully) before"| worker
    migrate -->|"must complete (service_completed_successfully) before"| api

    worker -->|app_writer| tables
    api -->|app_writer| tables
    api -->|"ai_reader, read-only"| aiviews
    aiviews -->|"reads through views only"| tables
    api -->|"Notes + query rows leave the machine here"| anthropic

    browser -->|"page load"| web
    browser -->|"REST /api/v1 + SSE /api/v1/chat"| api
```

## 3. Ingest: sources and the startup chain (not a C4 diagram)

Look at which external source feeds which job on its regular schedule (thin arrows), and separately, the thick arrows tracing the worker's one-time startup chain: `constituents_sync` then `calendar_sync`, then `bars_backfill` and `edgar_sync` in parallel, then `market_caps_rebuild`, before the regular schedule registers.

```mermaid
flowchart TD
    subgraph sources["Sources"]
        wiki["Wikipedia"]
        alpaca["Alpaca"]
        sec["SEC EDGAR"]
    end

    cs["constituents_sync (startup + daily 06:00)"]
    cal["calendar_sync (startup + daily 06:05)"]
    bb["bars_backfill (startup, then hourly until done)"]
    bd["bars_daily (Trading Days 16:30)"]
    qp["quotes_poll (every 15s, market open)"]
    cas["corporate_actions_sync (daily 06:10)"]
    es["edgar_sync (startup + Sundays 07:00)"]
    mcr["market_caps_rebuild (after bars_daily/edgar_sync + nightly 21:00)"]
    gc["gap_check (nightly 21:30)"]

    wiki --> cs
    alpaca --> cal
    alpaca --> bb
    alpaca --> bd
    alpaca --> qp
    alpaca --> cas
    sec --> es

    cs ==>|"startup chain: 1st"| cal
    cal ==>|"2nd, in parallel"| bb
    cal ==>|"2nd, in parallel"| es
    bb ==>|"3rd, both must finish"| mcr
    es ==>|"3rd, both must finish"| mcr
    mcr -.->|"regular schedule registers only after this chain finishes"| qp
```

## 4. Ingest: jobs, tables, and triggers (not a C4 diagram)

Look at the `backfill_completed_at` gate (a Listing must clear `bars_backfill` before `bars_daily` or `gap_check` will touch it), the `refetch_requests` table standing in for the old in-memory queue for both the drift check and gap retries, and the `rerun_requested` loop on `market_caps_rebuild`.

```mermaid
flowchart TD
    cs["constituents_sync"]
    cal["calendar_sync"]
    bb["bars_backfill"]
    bd["bars_daily"]
    qp["quotes_poll"]
    cas["corporate_actions_sync"]
    es["edgar_sync"]
    mcr["market_caps_rebuild"]
    gc["gap_check"]
    prune["ingest_runs_prune (nightly 22:00)"]

    tCompanies[("companies, listings")]
    gate{{"listings.backfill_completed_at"}}
    tEvents[("events")]
    tTradingDays[("trading_days")]
    tBars[("daily_bars")]
    tQuotes[("quotes")]
    tShares[("shares_outstanding")]
    tMarketCaps[("market_caps")]
    tRefetch[("refetch_requests")]
    tIngestRuns[("ingest_runs")]

    cs -->|writes| tCompanies
    cs -->|"writes (index_added)"| tEvents
    cs -->|"new Listing: starts null"| gate
    cal -->|"writes (replaces future rows)"| tTradingDays
    bb -->|writes| tBars
    bb -->|"sets once a symbol's history is complete"| gate
    bd -->|writes| tBars
    qp -->|"writes (if observed_at newer)"| tQuotes
    cas -->|writes| tEvents
    es -->|writes| tShares
    es -->|"writes (10-K/10-Q/8-K)"| tEvents
    mcr -->|writes| tMarketCaps
    prune -->|"deletes old rows"| tIngestRuns

    gate -->|"gates (must be set)"| bd
    gate -->|"gates (must be set)"| gc

    drift{"drift check: stored adj_close vs new > 1e-6 relative?"}
    bd -->|"re-fetch last 5 Trading Days"| drift
    drift -->|"yes: insert before upserting"| tRefetch
    tRefetch -->|"reason=adj_drift, from_date"| bb

    gapfound["Trading Days with no bar found"]
    gc --> gapfound
    gapfound -->|"insert, reason=gap"| tRefetch
    tRefetch -->|"reason=gap, from_date, attempts += 1"| bb
    tRefetch -->|"3rd failed attempt: row deleted, accepted"| status["reported in /api/v1/status"]

    bd -->|triggers| mcr
    es -->|triggers| mcr
    rerun(("rerun_requested"))
    mcr -->|"already running: sets"| rerun
    rerun -->|"lock holder reruns once free"| mcr
```

## 5. Data model (ER diagram, not a C4 diagram)

Look at the primary keys, the writer noted in each entity's name (`worker`, `api`, or the checked-in `share_class_rules` seed), the `listings`-`quotes` relationship (exactly one Listing per Quote, zero-or-one Quote per Listing), and the two additions: `refetch_requests` and `share_class_rules.price_symbol`'s link to `listings`.

```mermaid
erDiagram
    companies["companies (worker)"] {
        text cik PK
        text name
        text sector
        boolean is_active
    }
    listings["listings (worker)"] {
        text symbol PK
        text cik FK
        boolean is_primary
        boolean is_active
        date first_bar_date
        timestamptz backfill_completed_at
    }
    share_class_rules["share_class_rules (seed, checked in)"] {
        text cik PK
        text price_symbol
        numeric shares_unit_ratio
        text note
    }
    trading_days["trading_days (worker)"] {
        date trade_date PK
        timestamptz open_at
        timestamptz close_at
    }
    daily_bars["daily_bars (worker)"] {
        text symbol PK
        date trade_date PK
        numeric close
        numeric adj_close
        bigint volume
        text source
    }
    quotes["quotes (worker)"] {
        text symbol PK
        numeric price
        timestamptz observed_at
        text feed
    }
    shares_outstanding["shares_outstanding (worker)"] {
        text cik PK
        date as_of_date PK
        text concept PK
        text accession PK
        bigint shares
    }
    market_caps["market_caps (worker)"] {
        text cik PK
        date trade_date PK
        numeric market_cap
        bigint shares_used
        boolean is_multi_class
    }
    events["events (worker)"] {
        bigserial id PK
        text cik FK
        text symbol
        date event_date
        text kind
    }
    notes["notes (api)"] {
        uuid id PK
        text cik FK
        date start_date
        date end_date
        text body
    }
    ingest_runs["ingest_runs (worker)"] {
        bigserial id PK
        text job
        text status
        timestamptz started_at
    }
    ingest_watermarks["ingest_watermarks (worker)"] {
        text job PK
        text key PK
        text value
    }
    refetch_requests["refetch_requests (worker)"] {
        text symbol PK
        text reason PK
        date from_date
        int attempts
        timestamptz requested_at
    }

    companies ||--o{ listings : "has"
    companies ||--o| share_class_rules : "seeded rule for"
    companies ||--o{ shares_outstanding : "reports"
    companies ||--o{ market_caps : "valued on Trading Day"
    companies ||--o{ events : "has"
    companies |o--o{ notes : "optionally about"
    listings ||--o{ daily_bars : "has"
    listings ||--o| quotes : "has current"
    listings ||--o| share_class_rules : "is price_symbol for"
    listings ||--o{ refetch_requests : "requested for"
    trading_days ||--o{ daily_bars : "on"
    trading_days ||--o{ market_caps : "on"
```

## 6. Live Quote path (sequence diagram, not a C4 diagram)

Look at the two independent loops: the worker polling Alpaca every 15 seconds and upserting only newer Quotes, and the browser polling `/api/v1/market` every 10 seconds. Staleness now comes from that single response, with no second call to `/api/v1/status`.

```mermaid
sequenceDiagram
    participant W as worker (quotes_poll)
    participant ALP as Alpaca
    participant DB as Postgres
    participant API as api (/api/v1)
    participant B as Browser (TanStack Query)

    loop every 15s while market is open
        W->>ALP: GET /v2/clock (cached 60s)
        W->>ALP: GET /v2/stocks/snapshots ("feed=iex", batches of 100)
        ALP-->>W: latestTrade.p, latestTrade.t
        W->>DB: upsert quotes ("app_writer", only if observed_at is newer)
    end

    loop every 10s while open, every 5 min while closed
        B->>API: GET /api/v1/market
        API->>DB: read active listings joined with quotes
        DB-->>API: rows
        API-->>B: symbol, price, observed_at, change, market_cap, server_time, is_open, next_open, next_close
        Note over B: staleness and next poll interval computed client-side from this one response, no separate /api/v1/status call
    end
```

## 7. Ask (AI) request (sequence diagram, not a C4 diagram)

Look at the two-step split: `run_sql` finishes a step before `show_table`/`show_chart` can read its `result_id` on the next model call. The bottom `alt` is the only top-level branch: normal completion, a mid-stream error that closes every open part first, or a client disconnect that cancels both the model stream and the query and sends nothing more.

```mermaid
sequenceDiagram
    participant B as Browser (useChat)
    participant API as api (/api/v1/chat)
    participant C as Claude
    participant G as run_sql guard
    participant DB as Postgres (ai_reader)

    B->>API: POST messages
    API-->>B: start

    Note over API,DB: Step N: run_sql
    API->>C: model call
    C-->>API: tool_use "run_sql(sql)"
    API-->>B: tool-input-available
    API->>G: guard, then run as ai_reader
    G->>DB: "read-only, timeouts, wrapped with LIMIT 5001"
    DB-->>G: rows
    G-->>API: "result_id, columns, rows"
    API-->>B: tool-output-available
    API-->>B: finish-step
    Note over G,API: "a guard or SQL error surfaces as tool-output-error instead, and the model can retry with a fixed query on a later step"

    Note over API,B: Step N+1: show_table / show_chart, using step N's result_id
    API->>C: model call
    C-->>API: tool_use "show_table/show_chart(result_id)"
    API-->>B: tool-input-available, tool-output-available
    API-->>B: data-view "ViewSpec"
    API-->>B: finish-step

    alt normal completion
        API-->>B: finish
        API-->>B: "data: [DONE]"
    else model error or budget exhausted
        Note over API: closes every open part first ("text-end", "tool-output-error" per unfinished call)
        API-->>B: error
        API-->>B: finish
    else client disconnects
        Note over API,DB: checked between every chunk via "request.is_disconnected()"
        B--xAPI: disconnect
        API->>C: cancel the Anthropic stream
        API->>DB: cancel the running query
        Note over API: nothing further is sent
    end
```

## 8. Job run lifecycle (state diagram, not a C4 diagram)

Look at the fork right after the trigger (`skipped_locked`, `skipped`, or `running`), the `rerun_requested` loop back into `Running` when a locked job is retriggered, the "lock connection lost" path straight to `failed`, and orphan cleanup, which now fires at any age, not just at startup.

```mermaid
stateDiagram-v2
    [*] --> AttemptingLock: "job trigger fires"

    AttemptingLock --> SkippedLocked: "lock held by another run"
    AttemptingLock --> Skipped: "job inputs are empty"
    AttemptingLock --> Running: "lock acquired, ingest_runs row inserted"

    SkippedLocked --> RerunRequested: "sets rerun_requested"
    RerunRequested --> Running: "lock holder reruns once free"

    Running --> Succeeded: "no item failures"
    Running --> Partial: "one or more items failed"
    Running --> Failed: "uncaught error"
    Running --> Failed: "lock connection lost mid-run"

    Skipped --> [*]: "status = skipped"
    SkippedLocked --> [*]: "no rerun requested"
    Succeeded --> [*]: "status = succeeded"
    Partial --> [*]: "status = partial"
    Failed --> [*]: "status = failed"

    state "Orphan cleanup: checked at every trigger, any age" as Orphan
    Running --> Orphan: "a running row for this job already exists and the lock can be acquired"
    Orphan --> Failed: "marked failed (orphaned)"
```

## 9. Startup order (not a C4 diagram)

Look at the join before `web`: both `api` becoming ready and the worker's own startup chain (diagram 3) have to finish, not just `migrate`.

```mermaid
flowchart LR
    db["db healthy (pg_isready)"] --> migrate["migrate completes (alembic upgrade head)"]
    migrate --> apiReady["api ready (/api/v1/health/ready)"]
    migrate --> workerChain["worker startup chain (constituents_sync, calendar_sync, bars_backfill ∥ edgar_sync, market_caps_rebuild)"]
    apiReady --> web["web (next dev, 127.0.0.1:3000)"]
    workerChain --> web
```
