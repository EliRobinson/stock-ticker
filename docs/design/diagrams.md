# System Design Diagrams

Mermaid renderings of the design in [system-design.md](system-design.md), using the terms defined in [CONTEXT.md](../../CONTEXT.md).

## 1. System context and containers

Look at which external source feeds which compose service, and which Postgres role (`app_writer` or `ai_reader`) each edge into `db` uses. Every compose port binds to `127.0.0.1`; `db` is not published at all.

```mermaid
flowchart LR
    subgraph external["External sources"]
        alpaca["Alpaca (clock, calendar, snapshots, bars, corporate actions)"]
        edgar["SEC EDGAR (companyfacts, submissions)"]
        wiki["Wikipedia (S&P 500 table)"]
        anthropic["Anthropic"]
    end

    subgraph compose["Docker Compose (all ports bound to 127.0.0.1)"]
        worker["worker (APScheduler, no published port)"]
        db[("db: Postgres 17 (not published)")]
        api["api (FastAPI, 127.0.0.1:8000)"]
        web["web (Next.js 16, 127.0.0.1:3000)"]
    end

    browser(["Browser"])

    alpaca --> worker
    edgar --> worker
    wiki --> worker
    worker -->|app_writer| db
    api -->|app_writer| db
    api -->|ai_reader, read-only| db
    api -->|"Claude tool loop"| anthropic

    browser -->|"page load"| web
    browser -->|"REST /api/v1 + SSE /api/v1/chat"| api
```

## 2. Ingest schedule and data flow

Look at which job writes which tables, and the three trigger chains: `bars_daily`'s drift check queuing a full adjusted re-fetch, `bars_daily`/`edgar_sync` both triggering `market_caps_rebuild`, and `gap_check` queuing its own re-fetch.

```mermaid
flowchart TD
    subgraph sources["Sources"]
        wiki["Wikipedia"]
        alpaca["Alpaca"]
        sec["SEC EDGAR"]
    end

    cs["constituents_sync (startup + daily 06:00)"]
    cal["calendar_sync (startup + daily 06:05)"]
    bb["bars_backfill (startup, hourly until done)"]
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

    tCompanies[("companies, listings")]
    tEvents[("events")]
    tTradingDays[("trading_days")]
    tBars[("daily_bars")]
    tQuotes[("quotes")]
    tShares[("shares_outstanding")]
    tMarketCaps[("market_caps")]

    cs -->|writes| tCompanies
    cs -->|"writes (index_added)"| tEvents
    cal -->|"writes (replaces future rows)"| tTradingDays
    bb -->|writes| tBars
    bd -->|writes| tBars
    qp -->|"writes (if observed_at newer)"| tQuotes
    cas -->|writes| tEvents
    es -->|writes| tShares
    es -->|"writes (10-K/10-Q/8-K)"| tEvents
    mcr -->|writes| tMarketCaps

    drift{"drift check: stored adj_close vs new adj_close > 1e-6 relative?"}
    bd -->|"re-fetch last 5 Trading Days"| drift
    drift -->|yes| refetch["full adjusted re-fetch for symbol"]
    refetch --> tBars

    bd -->|triggers| mcr
    es -->|triggers| mcr

    gapfound["Trading Days with no bar found"]
    gc --> gapfound
    gapfound -->|"re-fetch (up to 3 tries)"| tBars
    gapfound -->|"still open after 3 tries"| status["reported in /status"]
```

## 3. Data model

Look at the primary keys (composite where the design calls for one, such as `daily_bars` and `market_caps`), the foreign keys, and which tables sit outside the relationship graph entirely (`ingest_runs`, `ingest_watermarks` are job bookkeeping, not domain data).

```mermaid
erDiagram
    companies {
        text cik PK
        text name
        text sector
        boolean is_active
    }
    listings {
        text symbol PK
        text cik FK
        boolean is_primary
        boolean is_active
        date first_bar_date
    }
    share_class_rules {
        text cik PK
        text price_symbol
        numeric shares_unit_ratio
        text note
    }
    trading_days {
        date trade_date PK
        timestamptz open_at
        timestamptz close_at
    }
    daily_bars {
        text symbol PK
        date trade_date PK
        numeric close
        numeric adj_close
        bigint volume
    }
    quotes {
        text symbol PK
        numeric price
        timestamptz observed_at
        text feed
    }
    shares_outstanding {
        text cik PK
        date as_of_date PK
        text concept PK
        text accession PK
        bigint shares
    }
    market_caps {
        text cik PK
        date trade_date PK
        numeric market_cap
        bigint shares_used
        boolean is_multi_class
    }
    events {
        bigserial id PK
        text cik FK
        text symbol
        date event_date
        text kind
    }
    notes {
        uuid id PK
        text cik FK
        date start_date
        date end_date
        text body
    }
    ingest_runs {
        bigserial id PK
        text job
        text status
        timestamptz started_at
    }
    ingest_watermarks {
        text job PK
        text key PK
        text value
    }

    companies ||--o{ listings : "has"
    companies ||--o| share_class_rules : "seeded rule for"
    companies ||--o{ shares_outstanding : "reports"
    companies ||--o{ market_caps : "valued on Trading Day"
    companies ||--o{ events : "has"
    companies |o--o{ notes : "optionally about"
    listings ||--o{ daily_bars : "has"
    listings |o--o| quotes : "has current"
    trading_days ||--o{ daily_bars : "on"
    trading_days ||--o{ market_caps : "on"
```

## 4. Live Quote path

Look at the two independent loops: the worker polling Alpaca every 15 seconds and upserting only newer Quotes, and the browser polling `/api/v1/market` every 10 seconds and computing staleness itself from `observed_at` against `/status`'s `server_time`.

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
        API-->>B: symbol, price, observed_at, change, market_cap
        B->>API: GET /status
        API-->>B: server_time, market clock, data_as_of
        Note over B: staleness computed client-side "(server_time - observed_at)"
    end
```

## 5. Ask (AI) request

Look at the tool loop's inner `alt` (text versus a tool call), the SQL guard sitting between the model's `run_sql` call and `ai_reader`, and the disconnect path at the bottom where the API cancels both the model stream and the running query.

```mermaid
sequenceDiagram
    participant B as Browser (useChat)
    participant API as api (POST /api/v1/chat)
    participant C as Claude (tool loop)
    participant G as run_sql (SQL guard)
    participant DB as Postgres (ai_reader)

    B->>API: POST /api/v1/chat "{id, messages, trigger, messageId}"
    Note over API: UIMessage converter maps parts to Anthropic messages
    API-->>B: start "{messageId}"

    loop up to 8 steps, 60s wall time, 150k input tokens
        API-->>B: start-step
        API->>C: model call ("cached system prompt + tools")
        alt model answers in text
            C-->>API: text deltas
            API-->>B: text-start / text-delta / text-end
        else model calls a tool
            C-->>API: tool_use "run_sql(sql, purpose)"
            API-->>B: tool-input-available "{toolCallId, toolName, input}"
            API->>G: guard "(parse, ai.* table allow-list, function allow-list)"
            alt guard and query succeed
                G->>DB: "read-only transaction, local timeouts, SELECT wrapped with LIMIT 5001"
                DB-->>G: rows ("<=5000, cached under result_id")
                G-->>API: "{result_id, columns, rows, truncated}"
                API-->>B: tool-output-available "{toolCallId, output}"
                C-->>API: tool_use "show_table/show_chart(result_id, ...)"
                API-->>B: tool-input-available then tool-output-available
                API-->>B: data-view "{id, TableSpec|ChartSpec}"
            else guard rejects or query errors
                G-->>API: guard or SQL error text
                API-->>B: tool-output-error "{toolCallId, errorText}"
            end
        end
        API-->>B: finish-step
    end

    API-->>B: finish
    API-->>B: "data: [DONE]"

    Note over B,DB: Disconnect / cancel path
    API->>API: "checks request.is_disconnected() between chunks"
    B--xAPI: browser disconnects or aborts the stream
    API->>C: cancel the Anthropic stream
    API->>DB: cancel the running query
    API-->>B: error "{errorText}", then finish
```

## 6. Job run lifecycle

Look at the fork right after the advisory lock (`skipped_locked` versus `running`), the three terminal outcomes of a running job, and the separate orphan-cleanup path that fails any `running` row still open after an hour.

```mermaid
stateDiagram-v2
    [*] --> AttemptingLock: "job trigger fires (schedule or startup)"

    AttemptingLock --> SkippedLocked: "pg_try_advisory_lock(hashtext(job)) fails"
    AttemptingLock --> Running: "lock acquired, ingest_runs row inserted"

    Running --> Succeeded: "no item failures"
    Running --> Partial: "one or more items failed"
    Running --> Failed: "uncaught error"

    SkippedLocked --> [*]: "status = skipped_locked"
    Succeeded --> [*]: "status = succeeded"
    Partial --> [*]: "status = partial"
    Failed --> [*]: "status = failed"

    state "Orphan cleanup (on startup)" as Orphan
    Running --> Orphan: "running row older than 1h"
    Orphan --> Failed: "marked failed"
```
