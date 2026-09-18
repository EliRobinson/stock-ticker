'use client'

import type { SortingState } from '@tanstack/react-table'
import { useSearchParams } from 'next/navigation'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  chatBackendDown,
  chatChartAnswer,
  chatQueryFailed,
  chatStreaming,
  chatTableAnswer
} from '@/fixtures/chat'
import {
  alphabet,
  alphabetEvents,
  apple,
  appleEvents,
  buildBars,
  solventum,
  tsmc
} from '@/fixtures/company'
import {
  CLOSED_NOW,
  FIXTURE_NOW,
  marketApiDown,
  marketBackfill,
  marketClosed,
  marketEmpty,
  marketOpen,
  marketPartial,
  marketStale
} from '@/fixtures/market'
import { notes } from '@/fixtures/notes'
import {
  aiOk,
  aiSpent,
  statusBackfill,
  statusClosed,
  statusDegraded,
  statusFailing,
  statusFirstRun,
  statusMissingAlpaca,
  statusOk
} from '@/fixtures/status'
import type { MarketResponse, StatusResponse } from '@/lib/api'
import { companyHref } from '@/lib/routes'
import { cn } from '@/lib/utils'

import './board.css'

import { AskPanel } from '../ask/ask-panel'
import { askCopy } from '../ask/copy'
import type { ChatUIMessage as AskMessage } from '@/lib/chat'
import { prepareTurns } from '../ask/prepare'
import type { CompanyView } from '../company/company-screen'
import { parseRange } from '../company/range'
import { CompanyScreen, CompanySkeleton } from '../company/company-screen'
import type { CompanyScreenProps } from '../company/company-screen'
import { quotesProblemOf } from '../containers/market-container'
import { MarketScreen } from '../market/market-screen'
import type { QuotesProblem } from '../market/market-screen'
import { notesCopy } from '../notes/copy'
import { NoteForm } from '../notes/note-dialog'
import { NotesScreen, noFilters } from '../notes/notes-screen'
import type { NotesFilters } from '../notes/notes-screen'
import { Blueprint } from './blueprint'
import { ChangeCell, QuoteCell } from '../shared/cells'
import { MarkerLegend } from '../shared/marker-legend'
import {
  AiSpendPill,
  IngestHealthPill,
  MarketStatusPill
} from '../shared/status-pills'
import { AppShell } from '../shell/app-shell'
import type { Screen } from '../shell/app-shell'
import { Command } from '@/components/ui/command'
import { PaletteBody } from '../shell/command-palette'
import type { PaletteEntry } from '../shell/command-palette'
import { shellCopy } from '../shell/copy'
import { StatusStrip } from '../shell/status-strip'
import { boardCopy as copy } from './copy'

const noop = () => {}
const noSave = async () => {}
const TODAY = '2024-09-17'

const paletteEntries = marketOpen.listings.map((r) => ({
  cik: r.cik,
  symbol: r.symbol,
  name: r.name,
  price: r.price,
  change_pct: r.change_pct
}))

const companies = [apple, alphabet, solventum, tsmc].map((c) => ({
  cik: c.cik,
  label: `${c.listings[0]!.symbol} · ${c.name}`
}))
const symbolByCik = Object.fromEntries(
  [apple, alphabet, solventum, tsmc].map((c) => [c.cik, c.listings[0]!.symbol])
)
const appleBars = buildBars('AAPL')
const googBars = buildBars('GOOGL')
const solvBars = buildBars('SOLV')
const partialBars = buildBars('AAPL', '2024-09-17', 214)
const statusStale: StatusResponse = {
  ...statusDegraded,
  server_time: FIXTURE_NOW,
  market_clock: statusOk.market_clock
}
const quoteFor = (market: MarketResponse, symbol: string) =>
  market.listings.find((r) => r.symbol === symbol) ?? null

// ---- layout helpers -------------------------------------------------------

type Theme = 'light' | 'dark'

function Themed({
  theme,
  children,
  className
}: {
  theme: Theme
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(theme, 'bg-background text-foreground', className)}
      data-theme={theme}
    >
      {children}
    </div>
  )
}

function Frame({
  id,
  width,
  height,
  themes,
  children,
  className
}: {
  id: string
  width: number
  height?: number
  themes: Theme[]
  children: (theme: Theme) => ReactNode
  className?: string
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-label`}
      className='flex max-w-full flex-col gap-2.5'
    >
      <div className='flex items-baseline gap-2.5'>
        <span className='font-heading text-brand-strong text-sm tracking-[0.1em]'>
          {id}
        </span>
        <h3 id={`${id}-label`} className='font-sans text-sm font-medium'>
          {copy.frames[id]}
        </h3>
      </div>
      <div className='gap-4.5 flex max-w-full flex-wrap'>
        {themes.map((t) => (
          <div key={t} className='max-w-full overflow-x-auto p-1.5'>
            <Themed theme={t}>
              <Blueprint
                className={cn(
                  'bg-background flex flex-col overflow-hidden',
                  className
                )}
                style={{ width, height }}
              >
                {children(t)}
              </Blueprint>
            </Themed>
          </div>
        ))}
      </div>
    </section>
  )
}

function Group({ id, children }: { id: string; children: ReactNode }) {
  const [title, lede] = copy.groups[id] ?? [id, '']
  return (
    <div className='flex flex-col gap-5'>
      <div className='border-border flex flex-wrap items-baseline gap-3 border-b pb-2'>
        <h2 className='m-0 text-[26px]'>{title}</h2>
        <span className='text-muted-foreground text-sm'>{lede}</span>
      </div>
      <div className='flex flex-wrap items-start gap-10'>{children}</div>
    </div>
  )
}

// ---- screen harnesses -----------------------------------------------------

function MarketHarness({
  market,
  status,
  loading,
  problem,
  initialQuery = '',
  initialSector = null
}: {
  market: MarketResponse | null
  status: StatusResponse | null
  loading?: boolean
  problem?: QuotesProblem
  initialQuery?: string
  initialSector?: string | null
}) {
  const [query, setQuery] = useState(initialQuery)
  const [sector, setSector] = useState<string | null>(initialSector)
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'symbol', desc: false }
  ])
  return (
    <>
      <StatusStrip status={status} ai={aiOk} loading={!status} />
      <MarketScreen
        market={market}
        loading={loading}
        quotesProblem={problem ?? quotesProblemOf(status ?? undefined)}
        query={query}
        onQueryChange={setQuery}
        sector={sector}
        onSectorChange={setSector}
        sorting={sorting}
        onSortingChange={setSorting}
        onOpenCompany={noop}
      />
    </>
  )
}

function CompanyHarness({
  initialView,
  ...props
}: Partial<CompanyScreenProps> & {
  company: CompanyScreenProps['company']
  initialView?: Partial<CompanyView>
}) {
  const [view, setView] = useState<CompanyView>({
    range: parseRange(null),
    mode: 'line',
    tab: 'notes',
    ...initialView
  })
  const [symbol, setSymbol] = useState(
    props.company?.listings[0]?.symbol ?? 'AAPL'
  )
  return (
    <CompanyScreen
      symbol={symbol}
      onSymbolChange={setSymbol}
      quote={quoteFor(marketOpen, symbol)}
      serverTime={FIXTURE_NOW}
      isOpen
      bars={appleBars}
      notes={notes.filter((n) => n.cik === props.company?.cik)}
      events={
        props.company?.cik === alphabet.cik
          ? alphabetEvents.items
          : appleEvents.items
      }
      today={TODAY}
      onSaveNote={noSave}
      view={view}
      onViewChange={(v) => setView((prev) => ({ ...prev, ...v }))}
      {...props}
    />
  )
}

function AskHarness({
  messages,
  status = 'ready',
  ...rest
}: Partial<React.ComponentProps<typeof AskPanel>> & {
  messages: AskMessage[]
}) {
  return (
    <AskPanel
      turns={prepareTurns(messages, status)}
      status={status}
      onSend={noop}
      onClose={noop}
      {...rest}
    />
  )
}

function ShellHarness({
  screen,
  askOpen = false,
  collapsed,
  className,
  children
}: {
  screen: Screen
  askOpen?: boolean
  collapsed?: boolean
  className?: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(askOpen)
  const crumbs =
    screen === 'company'
      ? shellCopy.crumbs.company(apple.name)
      : screen === 'notes'
        ? shellCopy.crumbs.notes
        : shellCopy.crumbs.market
  return (
    <AppShell
      className={className}
      current={screen}
      crumbs={crumbs}
      status={statusOk}
      ai={aiOk}
      company={{ symbol: 'AAPL', href: companyHref(apple.cik) }}
      onNavigate={noop}
      paletteEntries={paletteEntries}
      onPaletteSelect={noop}
      askOpen={open}
      onAskOpenChange={setOpen}
      defaultCollapsed={collapsed}
      ask={
        <AskHarness messages={chatTableAnswer} onClose={() => setOpen(false)} />
      }
    >
      {children}
    </AppShell>
  )
}

function ScreenBody({ screen }: { screen: string }) {
  switch (screen) {
    case 'company':
      return <CompanyHarness company={apple} />
    case 'notes':
      return (
        <NotesScreen
          notes={notes}
          companies={companies}
          symbolByCik={symbolByCik}
          today={TODAY}
          filters={noFilters}
          onFiltersChange={noop}
          onSave={noSave}
          onDelete={noop}
        />
      )
    default:
      return (
        <MarketScreen
          market={marketOpen}
          query=''
          onQueryChange={noop}
          sector={null}
          onSectorChange={noop}
          sorting={[{ id: 'symbol', desc: false }]}
          onSortingChange={noop}
          onOpenCompany={noop}
        />
      )
  }
}

// ---- the board -----------------------------------------------------------

export function StatesBoard() {
  const params = useSearchParams()
  const screen = params.get('screen')
  const only = params.get('only')
  const themeParam = params.get('theme')
  const themes: Theme[] =
    themeParam === 'light'
      ? ['light']
      : themeParam === 'dark'
        ? ['dark']
        : ['light', 'dark']

  if (screen) {
    const s = (
      ['market', 'company', 'notes'].includes(screen) ? screen : 'market'
    ) as Screen
    return (
      <ShellHarness
        screen={s}
        askOpen={params.get('ask') === '1'}
        collapsed={params.get('collapsed') === '1' ? true : undefined}
      >
        <ScreenBody screen={s} />
      </ShellHarness>
    )
  }

  const show = (g: string) => !only || only === g

  return (
    <div className='bg-board text-foreground flex min-h-dvh flex-col gap-14 px-10 pb-24 pt-10 max-sm:px-4'>
      <header className='border-border flex flex-col gap-1.5 border-b pb-5'>
        <span className='font-heading text-muted-foreground text-xs uppercase tracking-[0.14em]'>
          {copy.kicker}
        </span>
        <h1 className='m-0 text-[46px] leading-none'>{copy.title}</h1>
        <p className='text-muted-foreground text-md m-0 max-w-[62ch] text-pretty'>
          {copy.intro}
        </p>
      </header>

      {show('G') && (
        <Group id='G'>
          <Frame id='G1' width={1440} height={812} themes={themes}>
            {() => (
              <ShellHarness
                screen='market'
                className='h-full'
                collapsed={false}
              >
                <ScreenBody screen='market' />
              </ShellHarness>
            )}
          </Frame>
          <Frame id='G2' width={1440} height={812} themes={themes}>
            {() => (
              <ShellHarness screen='market' className='h-full' collapsed>
                <ScreenBody screen='market' />
              </ShellHarness>
            )}
          </Frame>
          <Frame id='G3' width={1440} height={812} themes={themes}>
            {() => (
              <ShellHarness
                screen='market'
                className='h-full'
                collapsed
                askOpen
              >
                <ScreenBody screen='market' />
              </ShellHarness>
            )}
          </Frame>
          <Frame id='G4' width={1200} height={620} themes={themes}>
            {() => (
              <ShellHarness screen='notes' className='h-full' collapsed askOpen>
                <ScreenBody screen='notes' />
              </ShellHarness>
            )}
          </Frame>
        </Group>
      )}

      {show('M') && (
        <Group id='M'>
          <Frame id='M0' width={390} height={560} themes={themes}>
            {() => <MarketHarness market={marketStale} status={statusStale} />}
          </Frame>
          <Frame id='M1' width={880} height={420} themes={themes}>
            {() => <MarketHarness market={null} status={statusOk} loading />}
          </Frame>
          <Frame id='M2' width={560} height={320} themes={themes}>
            {() => (
              <MarketHarness market={marketEmpty} status={statusFirstRun} />
            )}
          </Frame>
          <Frame id='M3' width={560} height={320} themes={themes}>
            {() => (
              <MarketHarness
                market={marketOpen}
                status={statusOk}
                initialQuery='zzap'
                initialSector='Energy'
              />
            )}
          </Frame>
          <Frame id='M4' width={880} height={420} themes={themes}>
            {() => (
              <MarketHarness market={marketApiDown} status={statusFailing} />
            )}
          </Frame>
          <Frame id='M5' width={560} height={260} themes={themes}>
            {() => (
              <MarketHarness
                market={marketEmpty}
                status={statusMissingAlpaca}
              />
            )}
          </Frame>
          <Frame id='M6' width={880} height={360} themes={themes}>
            {() => <MarketHarness market={marketStale} status={statusStale} />}
          </Frame>
          <Frame id='M8' width={880} height={360} themes={themes}>
            {() => (
              <MarketHarness market={marketClosed} status={statusClosed} />
            )}
          </Frame>
          <Frame id='M9' width={880} height={380} themes={themes}>
            {() => (
              <MarketHarness market={marketBackfill} status={statusBackfill} />
            )}
          </Frame>
          <Frame id='M10' width={880} height={360} themes={themes}>
            {() => <MarketHarness market={marketPartial} status={statusOk} />}
          </Frame>
          <Frame id='M11' width={400} height={620} themes={themes}>
            {() => <MarketHarness market={marketOpen} status={statusOk} />}
          </Frame>
        </Group>
      )}

      {show('C') && (
        <Group id='C'>
          <Frame id='C1' width={1160} height={640} themes={themes}>
            {() => <CompanyHarness company={apple} />}
          </Frame>
          <Frame id='C2' width={1160} height={640} themes={themes}>
            {() => (
              <CompanyHarness
                company={alphabet}
                bars={googBars}
                initialView={{
                  mode: 'candles',
                  range: parseRange('5Y'),
                  tab: 'events'
                }}
              />
            )}
          </Frame>
          <Frame id='C3' width={880} height={420} themes={themes}>
            {() => <CompanySkeleton />}
          </Frame>
          <Frame id='C4' width={1160} height={560} themes={themes}>
            {() => <CompanyHarness company={apple} notes={[]} events={[]} />}
          </Frame>
          <Frame id='C5' width={880} height={420} themes={themes}>
            {() => <CompanyHarness company={apple} barsError />}
          </Frame>
          <Frame id='C6' width={880} height={200} themes={themes}>
            {() => (
              <CompanyHarness
                company={apple}
                quote={quoteFor(marketStale, 'AAPL')}
              />
            )}
          </Frame>
          <Frame id='C7' width={1160} height={600} themes={themes}>
            {() => (
              <CompanyHarness
                company={apple}
                bars={partialBars}
                initialView={{ range: parseRange('1M') }}
                backfill={{ loaded: 214, expected: 1753 }}
              />
            )}
          </Frame>
          <Frame id='C8' width={1160} height={600} themes={themes}>
            {() => (
              <CompanyHarness
                company={solventum}
                bars={solvBars}
                quote={quoteFor(marketOpen, 'SOLV')}
              />
            )}
          </Frame>
          <Frame id='C9' width={1160} height={600} themes={themes}>
            {() => (
              <CompanyHarness
                company={tsmc}
                bars={buildBars('TSM')}
                notes={notes.filter((n) => n.cik === tsmc.cik)}
                quote={quoteFor(marketOpen, 'TSM')}
              />
            )}
          </Frame>
          <Frame id='C9b' width={440} themes={themes} className='p-3.5'>
            {() => (
              <NoteForm
                inDialog={false}
                initial={{
                  cik: apple.cik,
                  start_date: '2024-08-05',
                  end_date: '2024-09-12',
                  body: 'Positioning unwind, not demand. Check monthly revenue prints before adding.'
                }}
                companies={[{ cik: apple.cik, label: `AAPL · ${apple.name}` }]}
                lockCompany
                origin='range'
                today={TODAY}
                onSave={noSave}
                onCancel={noop}
              />
            )}
          </Frame>
          <Frame id='C10' width={400} height={900} themes={themes}>
            {() => (
              <CompanyHarness
                company={apple}
                initialView={{ range: parseRange('1Y') }}
              />
            )}
          </Frame>
        </Group>
      )}

      {show('N') && (
        <Group id='N'>
          <Frame id='N1' width={780} height={640} themes={themes}>
            {() => <ScreenBody screen='notes' />}
          </Frame>
          <Frame id='N2' width={480} height={460} themes={themes}>
            {() => (
              <NotesScreen
                notes={[]}
                loading
                companies={companies}
                symbolByCik={symbolByCik}
                today={TODAY}
                filters={noFilters}
                onFiltersChange={noop}
                onSave={noSave}
                onDelete={noop}
              />
            )}
          </Frame>
          <Frame id='N3' width={480} height={300} themes={themes}>
            {() => (
              <NotesScreen
                notes={[]}
                companies={companies}
                symbolByCik={symbolByCik}
                today={TODAY}
                filters={noFilters}
                onFiltersChange={noop}
                onSave={noSave}
                onDelete={noop}
              />
            )}
          </Frame>
          <Frame id='N3b' width={480} height={300} themes={themes}>
            {() => <NotesFiltered />}
          </Frame>
          <Frame id='N4' width={480} height={220} themes={themes}>
            {() => (
              <NotesScreen
                notes={[]}
                error
                companies={companies}
                symbolByCik={symbolByCik}
                today={TODAY}
                filters={noFilters}
                onFiltersChange={noop}
                onSave={noSave}
                onDelete={noop}
              />
            )}
          </Frame>
          <Frame
            id='N5'
            width={480}
            height={260}
            themes={themes}
            className='relative p-3.5'
          >
            {() => <UndoToastPreview />}
          </Frame>
          <Frame id='N7' width={400} height={620} themes={themes}>
            {() => <ScreenBody screen='notes' />}
          </Frame>
        </Group>
      )}

      {show('A') && (
        <Group id='A'>
          <Frame id='A1' width={420} height={460} themes={themes}>
            {() => <AskHarness messages={[]} />}
          </Frame>
          <Frame id='A2' width={420} height={460} themes={themes}>
            {() => <AskHarness messages={chatStreaming} status='streaming' />}
          </Frame>
          <Frame id='A3' width={420} height={720} themes={themes}>
            {() => <AskHarness messages={chatTableAnswer} defaultSqlOpen />}
          </Frame>
          <Frame id='A4' width={420} height={520} themes={themes}>
            {() => <AskHarness messages={chatChartAnswer} />}
          </Frame>
          <Frame id='A5' width={420} height={320} themes={themes}>
            {() => (
              <AskHarness
                messages={chatBackendDown}
                status='error'
                error={askCopy.errors['backend-down']}
                onRetry={noop}
              />
            )}
          </Frame>
          <Frame id='A5b' width={420} height={320} themes={themes}>
            {() => <AskHarness messages={[]} unavailable='missing-key' />}
          </Frame>
          <Frame id='A5c' width={420} height={460} themes={themes}>
            {() => (
              <AskHarness
                messages={chatQueryFailed}
                status='error'
                error={askCopy.errors['query-failed']}
              />
            )}
          </Frame>
          <Frame id='A5d' width={420} height={320} themes={themes}>
            {() => (
              <AskHarness
                messages={[]}
                unavailable='spend-limit'
                spendLimit='$5.00'
              />
            )}
          </Frame>
          <Frame id='A6' width={400} height={560} themes={themes}>
            {() => <AskHarness messages={chatTableAnswer} compact />}
          </Frame>
        </Group>
      )}

      {show('S') && (
        <Group id='S'>
          <Frame
            id='S1'
            width={290}
            themes={themes}
            className='tabular gap-2.5 p-3'
          >
            {() => (
              <>
                <div>
                  <QuoteCell
                    price='227.52'
                    ageMs={12_000}
                    state='fresh'
                    className='text-xl font-bold'
                  />
                  <div className='text-muted-foreground text-2xs'>
                    {copy.quoteFresh}
                  </div>
                </div>
                <div>
                  <QuoteCell
                    price='142.18'
                    ageMs={14 * 60_000}
                    state='stale'
                    className='text-xl'
                  />
                  <div className='text-muted-foreground text-2xs'>
                    {copy.quoteStale}
                  </div>
                </div>
                <div>
                  <QuoteCell
                    price='117.32'
                    ageMs={null}
                    state='closed'
                    className='text-xl font-bold'
                  />
                  <div className='text-muted-foreground text-2xs'>
                    {copy.quoteClosed}
                  </div>
                </div>
              </>
            )}
          </Frame>
          <Frame
            id='S2'
            width={290}
            themes={themes}
            className='gap-2 p-3 text-base'
          >
            {() => (
              <>
                <ChangeCell pct='1.23' abs='3.14' />
                <ChangeCell pct='-0.41' abs='-1.71' />
                <ChangeCell pct='0' abs='0' />
                <span>
                  <ChangeCell pct='-0.41' abs='-1.71' stale />{' '}
                  <span className='text-stale text-2xs'>
                    {copy.staleVariant}
                  </span>
                </span>
              </>
            )}
          </Frame>
          <Frame
            id='S3'
            width={400}
            themes={themes}
            className='items-start gap-2 p-3'
          >
            {() => (
              <>
                <MarketStatusPill
                  clock={statusOk.market_clock}
                  serverTime={FIXTURE_NOW}
                />
                <MarketStatusPill
                  clock={statusClosed.market_clock}
                  serverTime={CLOSED_NOW}
                />
                <MarketStatusPill
                  clock={statusClosed.market_clock}
                  serverTime='2024-09-17T12:00:00Z'
                />
                <MarketStatusPill
                  clock={statusDegraded.market_clock}
                  serverTime={statusDegraded.server_time}
                />
              </>
            )}
          </Frame>
          <Frame
            id='S4'
            width={400}
            themes={themes}
            className='items-start gap-2 p-3'
          >
            {() => (
              <>
                <IngestHealthPill
                  health='ok'
                  detail={{
                    lastRunAt: '2024-09-17T15:42:02Z',
                    summary: 'quotes succeeded · bars 503/503'
                  }}
                />
                <IngestHealthPill
                  health='degraded'
                  detail={{
                    lastRunAt: '2024-09-17T20:30:00Z',
                    summary: '12 of 503 symbols timed out'
                  }}
                />
                <IngestHealthPill
                  health='failing'
                  detail={{
                    lastRunAt: '2024-09-17T15:41:50Z',
                    summary: 'Alpaca connection refused · 6 failed runs'
                  }}
                />
              </>
            )}
          </Frame>
          <Frame id='S5' width={400} themes={themes} className='p-3'>
            {() => <MarkerLegend note='Note · user-authored' />}
          </Frame>
          <Frame
            id='S6'
            width={560}
            themes={themes}
            className='p-5.5 items-center'
          >
            {() => (
              <PalettePreview
                entries={paletteEntries.filter((e) =>
                  ['NVDA', 'NVR', 'NI'].includes(e.symbol)
                )}
              />
            )}
          </Frame>
          <Frame
            id='S7'
            width={400}
            themes={themes}
            className='items-start gap-2 p-3'
          >
            {() => (
              <>
                <AiSpendPill
                  spendUsd={aiOk.spend_usd}
                  limitUsd={aiOk.limit_usd}
                />
                <AiSpendPill
                  spendUsd={aiSpent.spend_usd}
                  limitUsd={aiSpent.limit_usd}
                />
              </>
            )}
          </Frame>
        </Group>
      )}
    </div>
  )
}

function NotesFiltered() {
  const [filters, setFilters] = useState<NotesFilters>({
    ...noFilters,
    q: 'dividend'
  })
  return (
    <NotesScreen
      notes={notes.slice(0, 1)}
      companies={companies}
      symbolByCik={symbolByCik}
      today={TODAY}
      filters={filters}
      onFiltersChange={(f) => setFilters((prev) => ({ ...prev, ...f }))}
      onSave={noSave}
      onDelete={noop}
    />
  )
}

function PalettePreview({ entries }: { entries: PaletteEntry[] }) {
  const first = entries[0]
  return (
    <Blueprint className='bg-background w-[440px] max-w-full shadow-lg'>
      <Command
        label={shellCopy.palette.title}
        defaultValue={first ? `${first.symbol} ${first.name}` : undefined}
        className='bg-background'
      >
        <PaletteBody entries={entries} onSelect={noop} />
      </Command>
    </Blueprint>
  )
}

// Sonner renders the live toast; this is its resting state for the board.
function UndoToastPreview() {
  return (
    <>
      <div className='border-border border px-3 py-2.5'>
        <div className='tabular text-sm font-bold'>17 Sep 2024</div>
        <p className='m-0 text-sm'>{notes[0]!.body.slice(0, 44)}</p>
      </div>
      <div
        role='status'
        className='border-border bg-popover absolute inset-x-3.5 bottom-3.5 flex items-center gap-3 border px-3 py-2.5 shadow-md'
      >
        <span className='text-sm'>{notesCopy.deleted}</span>
        <Button variant='ghost' className='ml-auto'>
          {notesCopy.undo}
        </Button>
        <span
          aria-hidden='true'
          className='bg-track w-8.5 relative block h-[3px]'
        >
          <span className='bg-brand absolute inset-y-0 left-0 w-3/5' />
        </span>
      </div>
    </>
  )
}
