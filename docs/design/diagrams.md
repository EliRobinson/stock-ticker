# System Design Diagrams

Mermaid renderings of the design in [system-design.md](system-design.md), using the terms defined in [CONTEXT.md](../../CONTEXT.md).

## Requirements traceability

The four requirements from the design brief, the diagrams that show each one, the main components involved, and the tracking issues.

| Requirement                                                           | Diagrams                                                                                                                                                                                                                                                                                       | Main components                                                                                                                                                                                                                                                             | GitHub issues                                                                                                                                                                      |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R1**: S&P 500 price data kept as fresh as possible                  | [2](#2-containers-c4-level-2), [3 (worker)](#component-worker), [4 (R1)](#code-r1-fresh-sp-500-price-data), [5](#5-ingest-sources-and-the-startup-chain-not-a-c4-diagram), [6](#6-ingest-jobs-tables-and-triggers-not-a-c4-diagram), [8](#8-live-quote-path-sequence-diagram-not-a-c4-diagram) | `worker`, `QuoteSource`/`BarSource`, the Alpaca adapter (planned), `JobSpec`/`JobContext`/`run_job`, `upsert_quotes`/`upsert_bars`, `quotes_poll`, `bars_backfill`, `bars_daily`, `constituents_sync`, `calendar_sync`, `corporate_actions_sync`, `edgar_sync`, `gap_check` | [#4](https://github.com/EliRobinson/stock-ticker/issues/4), [#5](https://github.com/EliRobinson/stock-ticker/issues/5)                                                             |
| **R2**: tables and charts with data manipulation (zoom, filter, sort) | [3 (api, web)](#3-components-c4-level-3), [4 (R2)](#code-r2-tables-and-charts-with-data-manipulation), [7](#7-data-model-er-diagram-not-a-c4-diagram)                                                                                                                                          | `market`/`bars`/`companies` routers, `MarketRow`/`Bar` models, `useMarket`/`useBars`, the market-table lib, the chart-data lib, `market_caps_rebuild`                                                                                                                       | [#6](https://github.com/EliRobinson/stock-ticker/issues/6), [#8](https://github.com/EliRobinson/stock-ticker/issues/8), [#9](https://github.com/EliRobinson/stock-ticker/issues/9) |
| **R3**: notes tagged to dates or companies                            | [3 (api, web)](#3-components-c4-level-3), [4 (R3)](#code-r3-notes-tagged-to-dates-or-companies)                                                                                                                                                                                                | `notes` router, `Note`/`NoteCreate`/`NoteUpdate` models, `usePutNote`, chart marker snapping                                                                                                                                                                                | [#6](https://github.com/EliRobinson/stock-ticker/issues/6), [#9](https://github.com/EliRobinson/stock-ticker/issues/9)                                                             |
| **R4**: AI that builds and interacts with tables and charts           | [3 (api, web)](#3-components-c4-level-3), [4 (R4)](#code-r4-ai-that-builds-and-interacts-with-tables-and-charts), [9](#9-ask-ai-request-sequence-diagram-not-a-c4-diagram)                                                                                                                     | `chat` router, `ai.tools`/`ai.guard`/`ai.executor`/`ai.stream`/`ai.spend`, `ViewSpec`, the `useChat` transport                                                                                                                                                              | [#7](https://github.com/EliRobinson/stock-ticker/issues/7), [#8](https://github.com/EliRobinson/stock-ticker/issues/8), [#9](https://github.com/EliRobinson/stock-ticker/issues/9) |

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

## 3. Components (C4 Level 3)

One diagram per container, one level in from diagram 2. Each component is tagged with the requirement(s) it serves. Mermaid's native `C4Component` diagram type renders poorly on GitHub, so these use `flowchart` with subgraphs instead, checked to render cleanly with mermaid-cli.

Reflects [`feat/api-foundation`](https://github.com/EliRobinson/stock-ticker/tree/feat/api-foundation) @ `9436289fdc` for the `api` diagram, the same commit plus [`feat/ingest-reference`](https://github.com/EliRobinson/stock-ticker/tree/feat/ingest-reference) @ `9b5c63fe57` for the `worker` diagram, and the same commit plus [`feat/web-data`](https://github.com/EliRobinson/stock-ticker/tree/feat/web-data) @ `913e9decc0` for the hooks and lib layers of the `web` diagram. Its screens, containers, and shell have no branch yet (`feat/web-screens` doesn't exist), so those are drawn from the plan the #9 builder shared directly.

### Component: api

The `api` container: its HTTP routers, the AI module behind `POST /api/v1/chat`, and the two Postgres roles it connects as. Most routers below are still `501` stubs on `feat/api-foundation` (only `health` and `status` have real bodies), so this diagram is the shape the container is built around, not a claim that every edge already moves real data.

```mermaid
flowchart TD
    subgraph http["HTTP surface (/api/v1)"]
        health["health router [R1]"]
        status["status router [R1]"]
        market["market router [R1][R2]"]
        companies["companies router [R2]"]
        bars["bars router (listings.py) [R2]"]
        events["events router [R2]"]
        notes["notes router [R3]"]
        chat["chat router [R4]"]
    end

    subgraph aimod["AI module"]
        prompt["prompt builder, ai.prompt [R4]"]
        tools["tool definitions, ai.tools: run_sql, show_table, show_chart [R4]"]
        guard["SQL guard, ai.guard [R4]"]
        executor["executor, ai.executor, ai_reader role [R4]"]
        uimsg["UIMessage converter, ai.convert [R4]"]
        encoder["stream encoder, ai.stream [R4]"]
        spend["spend gate, ai.spend [R4]"]
    end

    subgraph cross["Cross-cutting"]
        problems["problem+json handlers"]
        appwriter["app_writer engine"]
        aireader["ai_reader engine"]
    end

    browser(["Browser"])
    pg[("Postgres")]
    anthropic(["Anthropic"])

    browser -->|"GET/POST/PATCH/DELETE"| http
    browser -->|"POST /api/v1/chat, SSE"| chat

    chat -->|"builds system prompt from ai schema comments"| prompt
    chat -->|"routes tool_use to"| tools
    tools -->|"run_sql input"| guard
    guard -->|"validated SQL"| executor
    chat -->|"UIMessage list in"| uimsg
    uimsg -->|"Anthropic messages"| prompt
    chat -->|"parts out"| encoder
    chat -->|"checked before each model call"| spend

    health -->|"reads"| appwriter
    status -->|"reads ingest_runs, listings"| appwriter
    market -->|"reads listings + quotes"| appwriter
    companies -->|"reads"| appwriter
    bars -->|"reads daily_bars"| appwriter
    events -->|"reads"| appwriter
    notes -->|"reads and writes"| appwriter
    executor -->|"SELECT only"| aireader

    appwriter -->|"app_writer role"| pg
    aireader -->|"ai_reader role, ai.* views"| pg

    http -->|"errors rendered as"| problems
    chat -->|"model call"| anthropic
```

### Component: worker

The `worker` container: the job registry and lifecycle, the source adapters, the sinks that write to Postgres, and the jobs that tie them together. The Alpaca adapters are drawn from spec: no `feat/ingest-alpaca` branch exists yet, only the `QuoteSource`/`BarSource` protocols they will implement.

```mermaid
flowchart TD
    subgraph registry["Job registry and lifecycle"]
        jobs["JOBS registry [R1]"]
        jobwrap["job wrapper: run_job [R1]"]
        startup["startup chain: run_startup_chain [R1]"]
        scheduler["scheduler, AsyncIOScheduler [R1]"]
    end

    subgraph adapters["Adapters"]
        alpacaq["Alpaca QuoteSource [R1]"]
        alpacab["Alpaca BarSource [R1]"]
        edgar["EDGAR adapter [R1]"]
        wiki["Wikipedia adapter [R1]"]
    end

    subgraph sinks["Sinks"]
        upq["upsert_quotes [R1]"]
        upb["upsert_bars [R1]"]
    end

    subgraph jobsg["Jobs"]
        cs["constituents_sync [R1]"]
        cal["calendar_sync [R1]"]
        bb["bars_backfill [R1]"]
        bd["bars_daily [R1]"]
        qp["quotes_poll [R1]"]
        cas["corporate_actions_sync [R1]"]
        es["edgar_sync [R1]"]
        mcr["market_caps_rebuild [R1][R2]"]
        gc["gap_check [R1]"]
        prune["ingest_runs_prune"]
    end

    alpacaSrc(["Alpaca"])
    edgarSrc(["SEC EDGAR"])
    wikiSrc(["Wikipedia"])
    pg[("Postgres, app_writer")]

    wiki -->|"parses S&P 500 table"| cs
    edgar -->|"companyfacts, submissions"| es
    alpacaq -->|"snapshot symbols"| qp
    alpacab -->|"daily_bars raw and all"| bb
    alpacab -->|"daily_bars last 5 days"| bd

    wiki -->|"HTTP GET"| wikiSrc
    edgar -->|"HTTP GET, 5 req per s"| edgarSrc
    alpacaq -->|"HTTP GET"| alpacaSrc
    alpacab -->|"HTTP GET"| alpacaSrc

    qp -->|"ProviderQuote list"| upq
    bb -->|"ProviderBar list"| upb
    bd -->|"ProviderBar list"| upb

    upq -->|"upsert if newer"| pg
    upb -->|"upsert on conflict"| pg
    cs -->|"upsert companies, listings"| pg
    cal -->|"replace future rows"| pg
    cas -->|"upsert events"| pg
    es -->|"upsert shares_outstanding, events"| pg
    mcr -->|"upsert market_caps"| pg
    gc -->|"insert refetch_requests"| pg
    prune -->|"delete old rows"| pg

    jobs -->|"one JobSpec per job"| jobsg
    jobwrap -->|"advisory lock, ingest_runs row"| jobsg
    startup -->|"runs once at boot"| jobsg
    scheduler -->|"cron or interval trigger"| jobsg
```

`constituents_sync`, `edgar_sync`, `market_caps_rebuild`, and `gap_check` are real, on `feat/ingest-reference`. That branch was built against an earlier revision of the job framework (plain `AsyncConnection` handlers registered with a `register()` call) and will need a small rebase onto `feat/api-foundation`'s current `JobContext`/`registry.JOBS` shape when it merges. `calendar_sync`, `bars_backfill`, `bars_daily`, `quotes_poll`, and `corporate_actions_sync` have no branch yet and are drawn from spec (system-design.md §4).

### Component: web

The `web` container: the shell, the four screens and their containers (all still planned, no `feat/web-screens` branch), and the TanStack Query hooks plus the `lib/` layer, which are real on `feat/web-data`. The `lib/api.ts` client is written against the target contract (an idempotent `PUT /api/v1/notes/{id}`, cursor pagination) rather than the `501` stubs currently on `feat/api-foundation`, by design: see the R3 code diagram below.

```mermaid
flowchart TD
    subgraph shellg["Shell (planned)"]
        appShell["AppShell: nav, command palette, theme [R1]"]
        statusStrip["StatusStrip: market status, data as of, backfill [R1]"]
    end

    subgraph screens["Screens (planned)"]
        marketScreen["MarketScreen, MarketTable/MarketList [R2]"]
        companyScreen["CompanyScreen, PriceChart, NotesEventsPanel [R2][R3]"]
        notesScreen["NotesScreen, NoteCard, NoteDialog [R3]"]
        askPanel["AskPanel, AI Elements, ViewTable/ViewChart [R4]"]
    end

    subgraph containers["Containers (planned)"]
        marketC["MarketContainer [R2]"]
        companyC["CompanyContainer [R2][R3]"]
        notesC["NotesContainer [R3]"]
        askC["AskContainer [R4]"]
    end

    subgraph hooks["TanStack Query hooks"]
        useMarket["useMarket [R1][R2]"]
        useBars["useBars [R2]"]
        useCompany["useCompany [R2]"]
        useEvents["useEvents [R2][R3]"]
        useNotes["useNotes, usePutNote, useDeleteNote [R3]"]
        useStatus["useStatus [R1]"]
    end

    subgraph libs["lib"]
        apiClient["api.ts: typed client, ApiError"]
        marketTable["market-table.ts: columns, sort, filter, URL state [R2]"]
        chartData["chart-data.ts: candlestick/volume mapping, marker snapping [R2][R3]"]
        chat["chat.ts: useStockTickerChat, ViewSpec schema [R4]"]
    end

    api(["api, /api/v1"])

    appShell -->|"job health, backfill progress"| statusStrip
    statusStrip --> useStatus

    marketScreen --> marketC
    companyScreen --> companyC
    notesScreen --> notesC
    askPanel --> askC

    marketC -->|"rows"| useMarket
    marketC -->|"sort, filter, virtualize"| marketTable
    companyC -->|"OHLC and adj_close"| useBars
    companyC -->|"company detail"| useCompany
    companyC -->|"event markers"| useEvents
    companyC -->|"note markers, range shading"| useNotes
    companyC -->|"series mapping"| chartData
    notesC -->|"list, mutate"| useNotes
    askC -->|"send and receive UIMessage"| chat
    askC -->|"render data-view table"| marketTable
    askC -->|"render data-view chart"| chartData

    useMarket -->|"GET /market"| apiClient
    useBars -->|"GET /listings/symbol/bars"| apiClient
    useCompany -->|"GET /companies/cik"| apiClient
    useEvents -->|"GET /events"| apiClient
    useNotes -->|"GET/PUT/DELETE /notes"| apiClient
    useStatus -->|"GET /status"| apiClient
    chat -->|"POST /chat, SSE"| api
    apiClient -->|"REST /api/v1"| api
```

## 4. Code (C4 Level 4)

One `classDiagram` per requirement, showing the key types and functions that implement it. Each diagram names the branch and commit it reflects; where the code doesn't exist yet, the classes are marked `from spec` or `planned` and the diagram is drawn from `system-design.md` or from what the owning builder shared directly.

### Code: R1, fresh S&P 500 price data

Real code from [`feat/api-foundation`](https://github.com/EliRobinson/stock-ticker/tree/feat/api-foundation) @ `9436289fdc`: the `QuoteSource`/`BarSource` protocols, `JobSpec`/`JobContext`/`run_job`, and `upsert_quotes`/`upsert_bars`. `AlpacaQuoteSource`/`AlpacaBarSource` have no branch yet (`feat/ingest-alpaca` doesn't exist) and are drawn from spec (system-design.md §4) as the two classes that will implement the existing protocols.

```mermaid
classDiagram
    class ProviderQuote {
        +str symbol
        +Decimal price
        +datetime observed_at
        +str feed
    }
    class ProviderBar {
        +str symbol
        +date trade_date
        +Decimal open
        +Decimal high
        +Decimal low
        +Decimal close
        +int volume
        +Decimal adj_close
        +str source
    }
    class QuoteSource {
        <<Protocol>>
        +snapshot(symbols) List~ProviderQuote~
        +stream(symbols) AsyncIterator~ProviderQuote~
    }
    class BarSource {
        <<Protocol>>
        +daily_bars(symbols, start, end) List~ProviderBar~
    }
    class AlpacaQuoteSource {
        <<from spec>>
        +snapshot(symbols) List~ProviderQuote~
        +stream(symbols) AsyncIterator~ProviderQuote~
    }
    class AlpacaBarSource {
        <<from spec>>
        +daily_bars(symbols, start, end) List~ProviderBar~
    }
    class JobSpec {
        +str name
        +BaseTrigger trigger
        +JobFn handler
        +bool trading_days_only
        +Tuple~RequiredKey~ requires_keys
        +resolved_misfire_grace_time() int
    }
    class JobContext {
        +AsyncEngine engine
        +int run_id
        +Settings settings
        +log
        +AsyncEngine quotes_engine
    }
    class JobResult {
        +int rows_written
        +List~FailedItem~ failed_items
    }
    class JobOutcome {
        +JobRunStatus status
        +JobResult result
        +dict error
    }
    class run_job {
        <<function>>
        +run_job(job_name, fn, engine, quotes_engine) JobOutcome
    }
    class upsert_quotes {
        <<function>>
        +upsert_quotes(conn, quotes) JobResult
    }
    class upsert_bars {
        <<function>>
        +upsert_bars(conn, bars) JobResult
    }

    QuoteSource <|.. AlpacaQuoteSource
    BarSource <|.. AlpacaBarSource
    QuoteSource ..> ProviderQuote : returns
    BarSource ..> ProviderBar : returns
    JobSpec --> JobContext : handler receives
    run_job --> JobContext : creates
    run_job --> JobOutcome : returns
    JobOutcome --> JobResult : wraps
    AlpacaQuoteSource ..> upsert_quotes : feeds
    AlpacaBarSource ..> upsert_bars : feeds
    upsert_quotes --> ProviderQuote : consumes
    upsert_bars --> ProviderBar : consumes
```

### Code: R2, tables and charts with data manipulation

`MarketRow`, `MarketResponse`, and `Bar` are real Pydantic models from [`feat/api-foundation`](https://github.com/EliRobinson/stock-ticker/tree/feat/api-foundation) @ `9436289fdc`. `ShareCount`, `Split`, `Rejection`, `CompanyRebuild`, `validate_counts`, and `rebuild_company` are real, from [`feat/ingest-reference`](https://github.com/EliRobinson/stock-ticker/tree/feat/ingest-reference) @ `9b5c63fe57` (`market_caps.py`). `marketTableColumns`, `MarketFilterState`, `useMarket`, `useBars`, `mapBarsToCandlestickSeries`, and `mapBarsToVolumeSeries` are also real, from [`feat/web-data`](https://github.com/EliRobinson/stock-ticker/tree/feat/web-data) @ `913e9decc0`.

```mermaid
classDiagram
    class MarketRow {
        <<real, api-foundation, models/market.py>>
        +str symbol
        +str cik
        +str name
        +str sector
        +Decimal price
        +datetime observed_at
        +Decimal prev_close
        +Decimal change
        +Decimal change_pct
        +int volume
        +Decimal market_cap
        +bool market_cap_is_approx
        +date first_bar_date
    }
    class MarketResponse {
        <<real, api-foundation>>
        +datetime server_time
        +MarketClock market_clock
        +List~MarketRow~ listings
    }
    class marketTableColumns {
        <<real, web-data, lib/market-table.ts>>
        +ColumnDef~MarketRow~[] columns
        +numericStringSortingFn
        +searchFilterFn, sectorFilterFn
    }
    class MarketFilterState {
        <<real, web-data, lib/market-table.ts>>
        +str q
        +str sector
        +sort: id, desc
    }
    class useMarket {
        <<real, web-data, hooks/useMarket.ts>>
        +queryKey marketKeys.all
        +refetchInterval: 10s open, 5min closed, from market_clock.is_open
        +data MarketResponse
    }
    class useBars {
        <<real, web-data, hooks/useBars.ts>>
        +queryKey barsKeys.list(symbol, params)
        +staleTime 1h
        +placeholderData keepPreviousData
        +data List~Bar~
    }
    class Bar {
        <<real, api-foundation, models/bars.py>>
        +date trade_date
        +Decimal open
        +Decimal high
        +Decimal low
        +Decimal close
        +Decimal adj_close
        +int volume
    }
    class mapBarsToCandlestickSeries {
        <<function, real, web-data, lib/chart-data.ts>>
        +mapBarsToCandlestickSeries(bars) CandlestickData
    }
    class mapBarsToVolumeSeries {
        <<function, real, web-data, lib/chart-data.ts>>
        +mapBarsToVolumeSeries(bars) VolumeBar
    }
    class ShareCount {
        <<real, ingest-reference, market_caps.py>>
        +date as_of_date
        +date filed_date
        +str concept
        +str accession
        +int shares
        +anchor_date date
    }
    class Split {
        <<real, ingest-reference>>
        +date ex_date
        +Decimal ratio
    }
    class Rejection {
        <<real, ingest-reference>>
        +ShareCount count
        +str reason
    }
    class CompanyRebuild {
        <<real, ingest-reference>>
        +int upserted
        +int removed
        +List~Rejection~ rejections
        +bool no_whole_company_count
    }
    class validate_counts {
        <<function, real, ingest-reference>>
        +validate_counts(counts, exemption_dates) tuple
    }
    class rebuild_company {
        <<function, real, ingest-reference>>
        +rebuild_company(conn, cik) CompanyRebuild
    }

    MarketResponse --> MarketRow
    useMarket --> MarketResponse : fetches
    useMarket ..> marketTableColumns : rows feed
    marketTableColumns --> MarketFilterState : sort/filter state
    useBars --> Bar : fetches
    useBars ..> mapBarsToCandlestickSeries : rows feed
    useBars ..> mapBarsToVolumeSeries : rows feed
    rebuild_company --> ShareCount : loads
    rebuild_company --> Split : loads
    rebuild_company --> validate_counts : calls
    validate_counts --> Rejection : produces
    rebuild_company --> CompanyRebuild : returns
    CompanyRebuild --> Rejection
    rebuild_company ..> MarketRow : market_cap column sourced from
```

### Code: R3, notes tagged to dates or companies

`Note` is a real Pydantic model on [`feat/api-foundation`](https://github.com/EliRobinson/stock-ticker/tree/feat/api-foundation) @ `9436289fdc`, but that commit's `notes` router has only `POST`, `PATCH`, and `DELETE` handlers, all still `501` stubs: no `PUT /notes/{id}` route exists server-side yet. `PutNoteBody`, `putNote`, `createNoteId`, `usePutNote`, `notesKeys`, `upsertNoteInPages`, `mapNotesToMarkers`, `snapToLoadedBar`, and `ChartMarker` are all real, from [`feat/web-data`](https://github.com/EliRobinson/stock-ticker/tree/feat/web-data) @ `913e9decc0`. The web client is written against the target contract (system-design.md §5's idempotent `PUT`) ahead of the API route existing, by design (`lib/api.ts`'s own comment says so), so calling it today 501s until the API side ships.

```mermaid
classDiagram
    class Note {
        <<real type, api-foundation models/notes.py + web-data api-types.ts>>
        +UUID id
        +str cik
        +date start_date
        +date end_date
        +str body
        +datetime created_at
        +datetime updated_at
    }
    class PutNoteBody {
        <<real, web-data, lib/api.ts>>
        +str cik
        +str start_date
        +str end_date
        +str body
    }
    class putNote {
        <<function, real, web-data, lib/api.ts>>
        +putNote(id, body) Note
        +PUT /api/v1/notes/id, not yet routed server-side
    }
    class createNoteId {
        <<function, real, web-data, hooks/useNotes.ts>>
        +createNoteId() str
    }
    class usePutNote {
        <<real, web-data, hooks/useNotes.ts>>
        +mutationFn putNote
        +onMutate: optimistic write into every notesKeys page
        +onError: rollback to snapshot
        +onSettled: invalidate notesKeys
    }
    class notesKeys {
        <<real, web-data, hooks/useNotes.ts>>
        +all
        +list(params) QueryKey
    }
    class upsertNoteInPages {
        <<function, real, web-data, hooks/useNotes.ts>>
        +upsertNoteInPages(data, note) NotesInfiniteData
    }
    class mapNotesToMarkers {
        <<function, real, web-data, lib/chart-data.ts>>
        +mapNotesToMarkers(notes, bars) MappedNotes
    }
    class snapToLoadedBar {
        <<function, real, web-data, lib/chart-data.ts>>
        +snapToLoadedBar(dateStr, dates) str or null
    }
    class ChartMarker {
        <<real, web-data, lib/chart-data.ts>>
        +str id
        +kind: note or event
        +str time
        +str text
    }

    usePutNote --> putNote : mutationFn
    putNote ..> PutNoteBody : sends
    putNote --> Note : returns
    usePutNote --> createNoteId : caller supplies id
    usePutNote --> notesKeys : optimistic write via
    usePutNote --> upsertNoteInPages : onMutate calls
    mapNotesToMarkers ..> Note : reads
    mapNotesToMarkers --> snapToLoadedBar : calls
    mapNotesToMarkers --> ChartMarker : produces
```

### Code: R4, AI that builds and interacts with tables and charts

`TableColumn`, `TableSpec`, `ChartSeries`, `TimeseriesChartSpec`, and `ViewSpec` are real, from [`feat/api-foundation`](https://github.com/EliRobinson/stock-ticker/tree/feat/api-foundation) @ `9436289fdc` (`models/views.py`). `chat.py` on that commit is a `501` stub, and no `feat/ai-chat` branch exists yet. Everything else here is `planned`, using the class and module names (`ai.tools`, `ai.guard`, `ai.executor`, `ai.stream`, `ai.spend`) the #7 builder shared directly ahead of that branch being pushed, not a guess from system-design.md §6 alone.

```mermaid
classDiagram
    class ToolDefinition {
        <<planned, ai.tools>>
        +str name
        +type input_model
    }
    class RunSqlTool {
        <<planned, ai.tools, RUN_SQL>>
        +str sql
        +str purpose
    }
    class ShowTableTool {
        <<planned, ai.tools, SHOW_TABLE>>
        +str result_id
        +str title
        +list columns
    }
    class ShowChartTool {
        <<planned, ai.tools, SHOW_CHART>>
        +str result_id
        +str title
        +str x
        +list series
        +str y_format
    }
    class AnswerTools {
        <<planned, ai.tools>>
        +cache: result_id to rows
    }
    class GuardedQuery {
        <<planned, ai.guard>>
        +str sql
    }
    class GuardError {
        <<planned, ai.guard>>
    }
    class guard_sql {
        <<function, planned, ai.guard>>
        +guard_sql(sql) GuardedQuery
    }
    class AiReaderExecutor {
        <<planned, ai.executor>>
        +execute(query) rows
    }
    class ToolError {
        <<planned, ai.executor>>
    }
    class TableColumn {
        <<real, models/views.py>>
        +str key
        +str label
        +str format
    }
    class TableSpec {
        <<real, models/views.py>>
        +str kind
        +str id
        +str title
        +List~TableColumn~ columns
        +List~dict~ rows
    }
    class ChartSeries {
        <<real, models/views.py>>
        +str key
        +str label
    }
    class TimeseriesChartSpec {
        <<real, models/views.py>>
        +str kind
        +str id
        +str title
        +str x
        +List~ChartSeries~ series
        +str y_format
        +List~dict~ rows
    }
    class ViewSpec {
        <<real, discriminated union>>
    }
    class UIMessageStreamEncoder {
        <<planned, ai.stream>>
        +encode(part) bytes
        +fail(error) void
    }
    class PostgresSpendLedger {
        <<planned, ai.spend>>
        +reserve(estimate) bool
        +settle(actual) void
    }
    class stream_answer {
        <<function, planned, ai.loop>>
        +stream_answer(deps, ui_messages, message_id)
    }

    stream_answer --> PostgresSpendLedger : reserve before each model call
    stream_answer --> AnswerTools : runs the tool loop
    RunSqlTool --> guard_sql : validates
    guard_sql --> GuardedQuery : returns
    guard_sql --> GuardError : or raises
    GuardedQuery --> AiReaderExecutor : runs
    AiReaderExecutor --> ToolError : or raises
    AiReaderExecutor --> AnswerTools : caches rows under result_id
    ShowTableTool --> TableSpec : builds
    ShowChartTool --> TimeseriesChartSpec : builds
    TableSpec --> TableColumn
    TimeseriesChartSpec --> ChartSeries
    TableSpec ..> ViewSpec : member of union
    TimeseriesChartSpec ..> ViewSpec : member of union
    stream_answer --> UIMessageStreamEncoder : emits parts through
    UIMessageStreamEncoder --> ViewSpec : streams data-view
    RunSqlTool --|> ToolDefinition
    ShowTableTool --|> ToolDefinition
    ShowChartTool --|> ToolDefinition
```

## 5. Ingest: sources and the startup chain (not a C4 diagram)

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

## 6. Ingest: jobs, tables, and triggers (not a C4 diagram)

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

## 7. Data model (ER diagram, not a C4 diagram)

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

## 8. Live Quote path (sequence diagram, not a C4 diagram)

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

## 9. Ask (AI) request (sequence diagram, not a C4 diagram)

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

## 10. Job run lifecycle (state diagram, not a C4 diagram)

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

## 11. Startup order (not a C4 diagram)

Look at the join before `web`: both `api` becoming ready and the worker's own startup chain (diagram 5) have to finish, not just `migrate`.

```mermaid
flowchart LR
    db["db healthy (pg_isready)"] --> migrate["migrate completes (alembic upgrade head)"]
    migrate --> apiReady["api ready (/api/v1/health/ready)"]
    migrate --> workerChain["worker startup chain (constituents_sync, calendar_sync, bars_backfill ∥ edgar_sync, market_caps_rebuild)"]
    apiReady --> web["web (next dev, 127.0.0.1:3000)"]
    workerChain --> web
```
