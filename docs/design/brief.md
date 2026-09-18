# Stock Ticker: UI Design Brief

## Purpose and audience

Stock Ticker is a local, single-user research tool for studying the S&P 500 Constituent List: how Companies have traded over time, what the user personally thinks about them, and questions answered by an AI agent with direct database access. The only user is its builder, working at a desk, usually alongside other tools. There is no onboarding, no multi-tenant concern, and no mobile use case to design for, but the window does get resized and split, so the layout must hold down to 400px without breaking. The tone throughout is that of a research terminal: dense, precise, quiet. It shows real numbers with their real uncertainty (a Quote can be stale, a Market Cap can be a quarter old, a Listing's history can start after 2018) rather than hiding those facts behind a clean-looking placeholder.

## Design principles

- **Numbers are the content.** Typography, spacing, and color exist to make prices, changes, and dates scannable at speed, not to decorate them.
- **Never claim more certainty than the data has.** A Stale Quote, a partial history, a filing-derived Market Cap, and a degraded ingest all say so, visibly, next to the number.
- **Dense but not cramped.** This is a single power user's tool, not a marketing surface. Favor information density over whitespace, but keep a 4px/8px rhythm so density doesn't read as clutter.
- **One voice for chrome text.** State the fact, the consequence, then the action. Stop there.
- **Keyboard-first.** Every screen is reachable and operable without a mouse.

## Global layout and navigation

A fixed left sidebar (icon + label, collapsible to icon-only) holds four destinations: Market, Company (only enabled once a Company is selected, otherwise disabled with a tooltip), Notes, and a persistent "Ask" toggle that opens/closes the AI panel rather than navigating away. Use shadcn/ui `Sidebar` (or `NavigationMenu` if `Sidebar` is unavailable in the installed version) plus `Tooltip` for the collapsed state's labels.

The AI panel is a right-hand `Sheet` (persistent/dockable, not a modal overlay) that can be open alongside any of the other three screens, resizable, with its own scroll region. Opening it does not navigate the main content away from what the user was looking at.

Global top bar: breadcrumb/page title on the left, `⌘K` command palette trigger (shadcn `Command` in a `CommandDialog`) on the right for jumping straight to a Company by symbol or name, plus a light/dark theme toggle (`DropdownMenu` with system/light/dark). The command palette is available from every screen via the keyboard shortcut, not just the visible button.

Root layout is a CSS grid: sidebar (fixed width, collapsible) / main content (fluid) / AI panel (fixed width when open, 0 when closed). At 400px width, the sidebar auto-collapses to icons-only and the AI panel becomes a full-width overlay `Sheet` instead of a side-by-side column.

## Screen 1: Market

**Purpose:** scan and enter the full Constituent List.

**Regions:**

- Header strip (full width, above the table): market status pill (open / closed / pre-market / after-hours, with next open/close time), "Data as of [timestamp]", ingest health pill (ok / degraded / failing), and, only while history is still loading, a backfill progress row ("History: 212 of 503 Listings").
- Toolbar: search `Input` (symbol or Company name, debounced), sector `Select` filter, result count.
- Table: virtualized with TanStack Table + TanStack Virtual inside a fixed-height container. Columns: symbol, Company name, sector, last Quote price, day change (% and $ together), Market Cap, volume, quote age. Every column is sortable via clickable header (`TableHead` with a sort-direction icon); sector and symbol/name are filterable from the toolbar.
- Row click navigates to the Company screen for that Listing's Company.

**Components:** shadcn `Table` primitives driving TanStack Table's headless model, `Input`, `Select`, `Badge` (status pills), `Skeleton`, `Tooltip` (quote-age and Market Cap hints), `Popover` (column header sort/filter affordance, optional).

**States:**

- _Loading (first paint):_ header strip renders immediately once market status is known; table body shows ~20 `Skeleton` rows at real row height so the virtualizer's scroll math doesn't jump on arrival.
- _Empty, first run, no data yet:_ centered empty state. Copy: "No Listings loaded. Ingest has not completed a first run. Start it from the terminal, or wait for the scheduled run." No CTA, this app has no in-UI ingest trigger.
- _Empty, search has no matches:_ "No Listings match '{query}'. Clear the search or adjust the sector filter." with a "Clear filters" button.
- _Error, API down:_ ingest health pill turns "failing"; a destructive `Alert` above the table reads: "Quotes are unavailable. The Alpaca connection is down. Prices last updated {timestamp}." Table still renders last-known Daily Bar data, each price marked stale.
- _Error, missing Alpaca key:_ same `Alert`, copy: "No Alpaca API key is configured. Quotes cannot load. Set ALPACA_KEY_ID and ALPACA_SECRET_KEY in .env and restart the app."
- _Stale data:_ any Quote older than the expected staleness window shows its age inline next to the price in muted text ("$142.18 · 14m old"), and the change cell uses a muted variant, never the normal up/down color, a Stale Quote is never shown as current.
- _Market closed:_ status pill reads "Closed · opens 9:30 AM ET"; Quote cells show the last close, age reflecting time since close, not treated as an error.
- _Backfill in progress:_ progress row shows "History: {n} of 503 Listings"; rows not yet backfilled show a `Skeleton` in the Market Cap/day-change cells rather than a zero or dash.
- _Partial data:_ a Listing whose history starts after 2018, or whose Market Cap is unavailable, shows "—" with a `Tooltip`: "History starts {date}" or "Market Cap unavailable, no filing on record."
- _Long text:_ Company names truncate with a `Tooltip` revealing the full name; the column has a max width, not a min width.
- _Narrow widths (400px):_ sector and Market Cap columns collapse first (hidden, reachable via a "Columns" `DropdownMenu`); symbol, price, and change stay visible always.

## Screen 2: Company

**Purpose:** study one Company's price history against its Notes and Events.

**Regions:**

- Header: Company name, sector, Listing switcher (`Tabs` or `Select` when a Company has more than one Listing, e.g. GOOGL/GOOG), key stats row (Market Cap with a "from filing dated {date}" `Tooltip`, 52-week range, day range).
- Chart: TradingView lightweight-charts instance in a client component. Main pane shows the Adjusted Close as a line series by default, with a toggle to candlesticks (built from the Daily Bar's as-traded OHLC); a synced volume histogram pane sits below. Range presets (1M/6M/YTD/1Y/5Y/Max) as a `ToggleGroup`, plus a custom range via two `Popover`-triggered `Calendar` date pickers.
- Markers: Notes and Events rendered via the chart's marker API, visually distinct shapes/colors (Notes: user-authored, filled circle; Events: sourced fact, outlined diamond). An `Popover`/`DropdownMenu`-driven Event-kind toggle list (splits, dividends, ticker changes, spin-offs, 10-K, 10-Q, 8-K, date added to S&P 500), splits and 8-K on by default, the rest off.
- Side panel: `Tabs` for "Notes" and "Events" lists scoped to this Company, each item showing its date/range and a snippet; clicking an item scrolls/highlights the corresponding chart marker.
- Note creation: clicking a date on the chart, or dragging to select a range, opens a `Dialog` (or inline `Popover` for a single date) with a markdown `Textarea` to write the Note, pre-filled with the Company and the selected date/range.

**Components:** `Tabs`, `ToggleGroup`, `Calendar` + `Popover` (date range), `Dialog`, `Textarea`, `Badge` (Event kind chips), `Skeleton`, `Tooltip`, `Separator`.

**States:**

- _Loading:_ stat row and chart show `Skeleton` blocks sized to final layout (a full-width rectangle, not a spinner, to avoid layout shift); side list shows 3–4 skeleton rows.
- _Empty, no Notes yet:_ Notes tab: "No Notes on {Company}. Click a date on the chart to add one." Events tab, when none exist: "No Events on record for this Company."
- _Error, chart data unavailable:_ chart area replaced with an `Alert`: "Price history is unavailable. The database connection failed. Stats and markers cannot load."
- _Stale data:_ if the Company's current Quote (in the stat row) is stale, same inline age treatment as the Market screen.
- _Market closed:_ no special chart treatment; the day-range stat reflects the last completed Trading Day.
- _Backfill in progress:_ chart shows the partial range available with a banner: "History loading, showing {n} of expected Trading Days." Range presets beyond the available data are disabled, not silently clipped.
- _Partial data:_ if history starts after 2018, "Max" simply starts there, with a caption under the chart: "History starts {date}." Unavailable Market Cap reads "—" with the same filing-based `Tooltip` as the Market screen.
- _Long text:_ Note bodies in the side list clamp to ~3 lines with a "Read more" disclosure; Company name in the header truncates with a `Tooltip`.
- _Narrow widths:_ side panel stacks under the chart below ~900px; at 400px, key stats wrap to two rows and the range `ToggleGroup` scrolls horizontally rather than wrapping.

## Screen 3: Notes

**Purpose:** manage all Notes across the whole app.

**Regions:**

- Toolbar: Company filter (`Select`, includes a "Whole market" option), date range filter (`Popover` + `Calendar`), text search `Input`.
- List: each Note as a `Card` or table row showing its date or range, its Company (or "Whole market"), and a markdown-rendered body preview. Edit and delete actions per item (`DropdownMenu` with Edit / Delete).
- Create: a persistent "New Note" `Button` opens the same `Dialog` used from the Company chart, minus a pre-filled Company/date.

**Components:** `Card` or `Table`, `Select`, `Calendar` + `Popover`, `Input`, `Dialog`, `Textarea`, `DropdownMenu`, `Toast` (Sonner-based shadcn toast) for delete-undo.

**States:**

- _Loading:_ 5–6 `Skeleton` card/row placeholders.
- _Empty, no Notes at all:_ "No Notes yet. Click 'New Note' to write one."
- _Empty, no results for filters/search:_ "No Notes match these filters. Clear the filters to see all Notes." with a "Clear filters" button.
- _Error:_ "Notes are unavailable. The database connection failed. Nothing can be created or edited until it recovers.", `Alert`, create button disabled.
- _Delete with undo:_ removes the row immediately and shows a `Toast`: "Note deleted." with an "Undo" action, 5-second window; after it expires the delete is final and silent.
- _Long text:_ body preview clamps at 3 lines with a "Read more" link that expands in place or opens the edit `Dialog` read-only.
- _Narrow widths:_ filter toolbar stacks vertically; Note cards go full width, one per row.

## Screen 4: Ask (AI)

**Purpose:** answer research questions against the database in natural language, from anywhere in the app.

**Regions:**

- Panel header: title "Ask", close control.
- Empty state: `Suggestion` chips with example prompts ("Which companies fell most when COVID struck (Feb 19 – Mar 23, 2020)?", "Top 10 Companies by Market Cap, 2020–2021").
- Conversation: AI Elements `Conversation` / `ConversationContent` containing `Message` items. Assistant messages render via `Response` (streamed markdown), and can embed a rendered `Table` (reusing the Market screen's table styling, non-virtualized for result sets this size) or a lightweight-charts time-series panel (same chart primitives as the Company screen, sized to the panel width).
- Tool progress: AI Elements `Tool` component shows in-flight steps ("Querying Daily Bars…") while the backend's tool loop runs, before the final answer streams in.
- SQL disclosure: a `Collapsible` ("Show SQL") under each answer, containing the query in AI Elements `CodeBlock`.
- Input: AI Elements `PromptInput` / `PromptInputTextarea` pinned to the panel's bottom, with a submit button and Enter-to-send / Shift+Enter-for-newline.
- Pin (stretch goal): a `Button` on an answer that saves the current table/chart view; out of scope for first-pass visuals beyond a disabled/ghost affordance.

**Components:** AI Elements `Conversation`, `Message`, `Response`, `Tool`, `Suggestion`, `PromptInput`, `CodeBlock`; shadcn `Collapsible`, `Button`, `Skeleton`, `Sheet` (panel container).

**States:**

- _Loading (panel first open, empty conversation):_ suggestion chips render immediately, nothing to skeleton.
- _Streaming an answer:_ `Tool` steps appear and resolve in order; the answer streams token by token via `Response`; an embedded table/chart appears only once its data is fully returned (no partial tables).
- _Empty, no query yet:_ covered by the Suggestion chips; no separate empty state needed.
- _Error, AI backend down:_ inline error bubble: "The answer could not be generated. The AI service is unreachable. Try the question again." with a retry `Button` on that message.
- _Error, missing AI key:_ panel-level `Alert` in place of the input: "AI answers are unavailable. No AI API key is configured. Set the key and restart the app." Input disabled.
- _Error, query failed against the database:_ "The answer could not be generated. The query failed against the database. Try rephrasing the question."
- _Stale/partial underlying data:_ a result touching a Stale Quote or a partial-history Company reuses the Market/Company screens' treatment, no separate visual language here.
- _Long text:_ long questions and answers wrap normally in `ConversationContent`; the SQL `CodeBlock` scrolls horizontally rather than wrapping.
- _Narrow widths:_ panel becomes a full-screen `Sheet` overlay; embedded tables drop optional columns the same way the Market table does.

## Shared components

- **Quote cell:** price in tabular numerals (`font-variant-numeric: tabular-nums` or a monospace/tabular numeral font). If stale, append age in muted secondary text and reduce the price's own emphasis.
- **Change cell:** always pairs a sign (`+`/`−`), an arrow icon (`↑`/`↓`), and color, up in green with `↑`/`+`, down in red with `↓`/`−`, flat in neutral gray with no arrow. Color is never the only signal (WCAG AA contrast on both light and dark; verify with `pnpm ds contracts`-equivalent contrast tooling if available, otherwise manual contrast check). Format: `+1.23%` and `+$3.14` shown together, e.g. "+1.23% (+$3.14)".
- **Market status pill:** `Badge` variants, open (solid green), closed (neutral gray), pre-market/after-hours (amber outline), each with the next open/close time as trailing text.
- **Ingest health pill:** `Badge`, ok (neutral/green), degraded (amber), failing (red), click opens a `Tooltip` or `Popover` with the last run's timestamp and outcome.
- **Chart marker legend:** small fixed legend near the chart, Note marker (filled circle) vs. Event marker (outlined diamond), with the Event-kind toggle list described in the Company screen.
- **AI result table/chart:** identical visual language to the Market table and Company chart, this is a hard constraint, not a suggestion, so an answer's chart looks like it belongs to the same app.
- **Number formatting:** Market Cap as `$2.91T` / `$487.2B` / `$3.4M` (largest applicable unit, 1 decimal); percentages as `+1.23%` / `−0.41%` (2 decimals, always signed); prices at native precision with tabular numerals throughout every screen and the AI panel.
- **Keyboard access:** every interactive element has a visible focus ring (not suppressed); `⌘K` opens the Company command palette from anywhere; `Tab` order follows visual order in every region including the AI panel; `Esc` closes any open `Dialog`/`Sheet`/`Popover`.
- **Theme:** full light and dark variants for every screen and every state above, including the destructive `Alert`, all `Badge` variants, and chart colors (lightweight-charts series/marker colors must be redefined per theme, not left at library defaults).

## Deliverables checklist

For each of the following, provide both light and dark theme:

- [ ] Market, loading, empty (first run), empty (no search results), error (API down), error (missing key), stale data, market closed, backfill in progress, partial data, narrow (400px)
- [ ] Company, loading, empty (no Notes/Events), error (data unavailable), stale data, market closed, backfill in progress, partial data (short history, missing Market Cap), long text, narrow (400px)
- [ ] Notes, loading, empty (no Notes), empty (no filter results), error, delete-with-undo toast, long text, narrow (400px)
- [ ] Ask, empty (suggestions), streaming (tool progress + partial answer), answer with table, answer with chart, SQL disclosure open, error (backend down), error (missing key), error (query failed), narrow/full-screen panel
- [ ] Shared components sheet, Quote cell, change cell (up/down/flat), market status pill (all four states), ingest health pill (all three states), chart marker legend, command palette (`⌘K`) open state
- [ ] Global, sidebar expanded/collapsed, AI panel open alongside each of the other three screens, focus-state pass on one representative screen
