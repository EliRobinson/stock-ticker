'use client'

import { ChevronDown, Info } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { DateRange } from 'react-day-picker'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'
import type {
  Bar,
  CompanyDetail,
  MarketEvent,
  MarketRow,
  Note
} from '@/lib/api'
import {
  mapBarsToCandlestickSeries,
  mapBarsToVolumeSeries,
  mapEventsToMarkers,
  mapNotesToMarkers
} from '@/lib/chart-data'
import { cn } from '@/lib/utils'

import type { PlacedMarker } from '../chart/markers-primitive'
import { PriceChart } from '../chart/price-chart'
import { NoteDialog } from '../notes/note-dialog'
import type { NoteDraft } from '../notes/note-dialog'
import { ChangeCell, ExplainedDash, TruncatedText } from '../shared/cells'
import { Kicker, SkeletonBar, StatusAlert } from '../shared/feedback'
import {
  formatAge,
  formatDate,
  formatDateRange,
  formatMarketCap,
  formatPrice
} from '../shared/format'
import { MarkerLegend } from '../shared/marker-legend'
import { quoteState } from '../shared/market-session'
import { Segmented } from '../shared/segmented'
import { companyCopy as copy } from './copy'
import { NotesEventsPanel } from './notes-events-panel'

export type RangePreset = '1M' | '6M' | 'YTD' | '1Y' | '5Y' | 'Max'
const PRESETS: RangePreset[] = ['1M', '6M', 'YTD', '1Y', '5Y', 'Max']

function presetStart(preset: RangePreset, last: string, first: string) {
  const d = new Date(`${last}T12:00:00Z`)
  switch (preset) {
    case '1M':
      d.setUTCMonth(d.getUTCMonth() - 1)
      break
    case '6M':
      d.setUTCMonth(d.getUTCMonth() - 6)
      break
    case 'YTD':
      return `${last.slice(0, 4)}-01-01`
    case '1Y':
      d.setUTCFullYear(d.getUTCFullYear() - 1)
      break
    case '5Y':
      d.setUTCFullYear(d.getUTCFullYear() - 5)
      break
    case 'Max':
      return first
  }
  return d.toISOString().slice(0, 10)
}

const DEFAULT_KINDS = ['splits', '8k']

export interface CompanyScreenProps {
  company: CompanyDetail | null
  loading?: boolean
  chartError?: boolean
  symbol: string
  onSymbolChange: (symbol: string) => void
  quote: MarketRow | null
  serverTime: string | null
  isOpen: boolean
  bars: Bar[] | null
  backfill?: { loaded: number; expected: number } | null
  notes: Note[]
  events: MarketEvent[]
  today: string
  onSaveNote: (draft: NoteDraft) => void
  noteSaveError?: string | null
  initialPreset?: RangePreset
  initialMode?: 'line' | 'candles'
  initialTab?: 'notes' | 'events'
}

export function CompanyScreen({
  company,
  loading = false,
  chartError = false,
  symbol,
  onSymbolChange,
  quote,
  serverTime,
  isOpen,
  bars,
  backfill = null,
  notes,
  events,
  today,
  onSaveNote,
  noteSaveError = null,
  initialPreset = 'Max',
  initialMode = 'line',
  initialTab = 'notes'
}: CompanyScreenProps) {
  const [preset, setPreset] = useState<RangePreset | null>(initialPreset)
  const [custom, setCustom] = useState<{ from: string; to: string } | null>(
    null
  )
  const [mode, setMode] = useState<'line' | 'candles'>(initialMode)
  const [kinds, setKinds] = useState<string[]>(DEFAULT_KINDS)
  const [highlighted, setHighlighted] = useState<string | null>(null)
  const [dialog, setDialog] = useState<{
    start: string
    end: string
    origin?: 'range' | 'date'
  } | null>(null)

  const candles = useMemo(
    () => (bars ? mapBarsToCandlestickSeries(bars) : []),
    [bars]
  )
  const chartBars = useMemo(
    () =>
      candles.map((c) => ({
        time: String(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close
      })),
    [candles]
  )
  const volume = useMemo(
    () =>
      bars
        ? mapBarsToVolumeSeries(bars).map((v) => ({
            time: String(v.time),
            value: v.value
          }))
        : [],
    [bars]
  )
  const firstDate = chartBars[0]?.time ?? ''
  const lastDate = chartBars[chartBars.length - 1]?.time ?? today

  const enabledKinds = useMemo(
    () =>
      new Set(
        copy.eventToggles
          .filter((t) => kinds.includes(t.id))
          .flatMap((t) => t.kinds as readonly string[])
      ),
    [kinds]
  )
  const shownEvents = useMemo(
    () => events.filter((e) => enabledKinds.has(e.kind)),
    [events, enabledKinds]
  )

  const { markers, outsideNoteIds } = useMemo(() => {
    if (!bars || bars.length === 0)
      return {
        markers: [] as PlacedMarker[],
        outsideNoteIds: new Set<string>()
      }
    const n = mapNotesToMarkers(notes, bars)
    const e = mapEventsToMarkers(shownEvents, bars)
    // #8 clips each Note range to loaded bars; the marker sits at its start.
    const rangeById = new Map(n.ranges.map((r) => [r.id, r]))
    const placed: PlacedMarker[] = [
      ...n.markers.map((m) => {
        const range = rangeById.get(m.id)
        return {
          id: m.id,
          kind: 'note' as const,
          barDate: m.time,
          start: range?.from ?? m.time,
          end: range?.to ?? m.time
        }
      }),
      ...e.markers.map((m) => ({
        id: `event-${m.id}`,
        kind: 'event' as const,
        barDate: m.time,
        start: m.time,
        end: m.time
      }))
    ]
    return {
      markers: placed,
      outsideNoteIds: new Set(n.outsideRange.map((x) => x.id))
    }
  }, [bars, notes, shownEvents])

  const visibleRange = useMemo(() => {
    if (!firstDate) return null
    if (custom) return custom
    if (!preset) return null
    const from = presetStart(preset, lastDate, firstDate)
    return { from: from < firstDate ? firstDate : from, to: lastDate }
  }, [custom, preset, firstDate, lastDate])

  const presetOptions = PRESETS.map((p) => {
    const beyond =
      p !== 'Max' &&
      firstDate !== '' &&
      presetStart(p, lastDate, firstDate) < firstDate
    return {
      value: p,
      label: p,
      disabled: beyond,
      title: beyond ? copy.presetDisabled : undefined
    }
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (
        target?.closest(
          'input, textarea, [contenteditable="true"], [role="dialog"]'
        )
      )
        return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const idx = Number(e.key) - 1
      if (idx >= 0 && idx < PRESETS.length && !presetOptions[idx]?.disabled) {
        setPreset(PRESETS[idx]!)
        setCustom(null)
      } else if (e.key.toLowerCase() === 'c') {
        setMode((m) => (m === 'line' ? 'candles' : 'line'))
      } else if (e.key.toLowerCase() === 'n' && company) {
        setDialog({ start: lastDate, end: lastDate })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [presetOptions, company, lastDate])

  if (loading || !company) return <CompanySkeleton />

  const q =
    quote && serverTime
      ? quoteState(quote.observed_at, serverTime, isOpen)
      : null
  const lastBar = bars?.[bars.length - 1]
  const partialHistory =
    company.first_bar_date != null && company.first_bar_date > '2018-01-02'
  const onKindsLabel = copy.eventToggles
    .filter((t) => kinds.includes(t.id))
    .map((t) => t.label)

  return (
    <div className='@container flex min-h-0 flex-1 flex-col overflow-auto'>
      <div className='@max-[900px]:grid-cols-1 grid grid-cols-[minmax(0,1fr)_330px]'>
        <div className='flex min-w-0 flex-col'>
          <div className='border-border flex flex-col gap-2.5 border-b p-3.5'>
            <div className='flex flex-wrap items-baseline gap-2.5'>
              <h1 className='m-0 min-w-0 max-w-[34ch] text-4xl'>
                <TruncatedText text={company.name} />
              </h1>
              <Badge variant='default'>{company.sector}</Badge>
              {company.listings.length > 1 && (
                <Segmented
                  label={copy.listing}
                  value={symbol}
                  onValueChange={onSymbolChange}
                  options={company.listings.map((l) => ({
                    value: l.symbol,
                    label: l.symbol
                  }))}
                  className='ml-auto'
                />
              )}
            </div>
            <dl className='gap-x-6.5 tabular @max-[560px]:grid @max-[560px]:grid-cols-2 m-0 flex flex-wrap gap-y-2.5'>
              <Stat label={isOpen ? copy.stats.last : copy.stats.lastClose}>
                {quote ? (
                  q?.stale ? (
                    <>
                      <span className='text-stale text-2xl'>
                        {formatPrice(quote.price)}{' '}
                        <span className='text-xs'>
                          {copy.stats.staleAge(formatAge(q.ageMs ?? 0))}
                        </span>
                      </span>
                      <ChangeCell
                        pct={quote.change_pct}
                        abs={quote.change}
                        stale
                        className='block text-sm'
                      />
                    </>
                  ) : (
                    <span className='text-2xl font-bold'>
                      {formatPrice(quote.price)}{' '}
                      <ChangeCell
                        pct={quote.change_pct}
                        abs={quote.change}
                        className='text-md font-normal'
                      />
                    </span>
                  )
                ) : (
                  <span className='text-2xl font-bold'>{'—'}</span>
                )}
              </Stat>
              <Stat
                label={
                  <span className='inline-flex items-center gap-1'>
                    {copy.stats.marketCap}
                    {company.market_cap && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type='button'
                            aria-label={copy.stats.fromFiling(
                              formatDate(company.market_cap.shares_as_of)
                            )}
                          >
                            <Info
                              aria-hidden='true'
                              className='size-[13px]'
                              strokeWidth={1.8}
                            />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>
                          {copy.stats.fromFiling(
                            formatDate(company.market_cap.shares_as_of)
                          )}
                          {company.market_cap.is_approx && (
                            <span className='block'>{copy.stats.approx}</span>
                          )}
                        </TooltipContent>
                      </Tooltip>
                    )}
                  </span>
                }
              >
                {company.market_cap ? (
                  <>
                    <span className='text-2xl font-bold'>
                      {company.market_cap.is_approx ? '≈' : ''}
                      {formatMarketCap(company.market_cap.market_cap)}
                    </span>
                    <span className='text-muted-foreground text-2xs block'>
                      {copy.stats.fromFiling(
                        formatDate(company.market_cap.shares_as_of)
                      )}
                    </span>
                  </>
                ) : (
                  <ExplainedDash
                    reason={copy.stats.capUnavailable}
                    className='text-2xl font-bold'
                  />
                )}
              </Stat>
              <Stat label={copy.stats.range52}>
                <span className='text-2xl font-bold'>
                  {formatPrice(company.week_52_low)} {'–'}{' '}
                  {formatPrice(company.week_52_high)}
                </span>
              </Stat>
              <Stat label={copy.stats.dayRange}>
                <span className='text-2xl font-bold'>
                  {lastBar
                    ? `${formatPrice(lastBar.low)} – ${formatPrice(lastBar.high)}`
                    : '—'}
                </span>
              </Stat>
            </dl>
          </div>

          {backfill && (
            <div
              role='status'
              aria-live='polite'
              className='border-border bg-pill-amber text-pill-amber-foreground tabular border-b px-3.5 py-2.5 text-sm'
            >
              {copy.backfill(backfill.loaded, backfill.expected)}
            </div>
          )}

          {chartError ? (
            <div className='p-3.5'>
              <StatusAlert centered title={copy.chartErrorTitle}>
                <span className='text-sm'>{copy.chartErrorBody}</span>
              </StatusAlert>
            </div>
          ) : (
            <>
              <div className='flex flex-wrap items-center gap-2.5 px-3.5 py-3'>
                <div className='max-w-full overflow-x-auto'>
                  <Segmented
                    label={copy.rangeLabel}
                    value={custom ? ('' as RangePreset) : (preset ?? 'Max')}
                    onValueChange={(v) => {
                      setPreset(v)
                      setCustom(null)
                    }}
                    options={presetOptions}
                  />
                </div>
                <CustomRange
                  value={visibleRange}
                  min={firstDate}
                  max={lastDate}
                  onChange={(r) => {
                    setCustom(r)
                    setPreset(null)
                  }}
                />
                <Segmented
                  label={copy.chartType}
                  value={mode}
                  onValueChange={setMode}
                  options={[
                    { value: 'line', label: copy.line },
                    { value: 'candles', label: copy.candles }
                  ]}
                  className='ml-auto'
                />
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant='outline'
                      className='font-sans text-sm font-normal'
                    >
                      {copy.events}
                      <ChevronDown
                        aria-hidden='true'
                        className='size-3.5'
                        strokeWidth={1.8}
                      />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align='end' className='w-56'>
                    <DropdownMenuLabel className='text-muted-foreground text-3xs font-normal uppercase tracking-[0.1em]'>
                      {copy.eventKinds}
                    </DropdownMenuLabel>
                    {copy.eventToggles.map((t) => (
                      <DropdownMenuCheckboxItem
                        key={t.id}
                        checked={kinds.includes(t.id)}
                        onSelect={(e) => e.preventDefault()}
                        onCheckedChange={(on) =>
                          setKinds((prev) =>
                            on
                              ? [...prev, t.id]
                              : prev.filter((k) => k !== t.id)
                          )
                        }
                      >
                        {t.label}
                      </DropdownMenuCheckboxItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <div className='px-3.5 pb-3.5'>
                {bars && bars.length > 0 ? (
                  <PriceChart
                    bars={chartBars}
                    volume={volume}
                    mode={mode}
                    markers={markers}
                    highlightedId={highlighted}
                    visibleRange={visibleRange}
                    onSelect={(start, end) =>
                      setDialog({
                        start,
                        end,
                        origin: start === end ? 'date' : 'range'
                      })
                    }
                    ariaLabel={copy.chartAria(company.name, mode)}
                  />
                ) : (
                  <SkeletonBar className='h-[308px]' />
                )}
                {partialHistory && company.first_bar_date && (
                  <p className='text-muted-foreground mt-2 text-xs'>
                    {copy.historyStarts(formatDate(company.first_bar_date))}
                  </p>
                )}
                <MarkerLegend
                  note={copy.legendNote}
                  event={copy.legendEvent}
                  hint={
                    mode === 'candles'
                      ? copy.candleHint
                      : copy.legendKinds(onKindsLabel)
                  }
                  className='border-border mt-2.5 border-t pt-2.5'
                />
              </div>
            </>
          )}
        </div>

        <NotesEventsPanel
          companyName={company.name}
          notes={notes}
          events={events}
          outsideNoteIds={outsideNoteIds}
          visibleRange={visibleRange}
          onHighlight={setHighlighted}
          highlightedId={highlighted}
          initialTab={initialTab}
          onNewNote={() => setDialog({ start: lastDate, end: lastDate })}
        />

        <NoteDialog
          open={dialog != null}
          onOpenChange={(open) => !open && setDialog(null)}
          initial={{
            cik: company.cik,
            start_date: dialog?.start ?? lastDate,
            end_date: dialog?.end ?? lastDate,
            body: ''
          }}
          companies={[
            { cik: company.cik, label: `${symbol} · ${company.name}` }
          ]}
          lockCompany
          origin={dialog?.origin}
          today={today}
          saveError={noteSaveError}
          onSave={(draft) => {
            onSaveNote(draft)
            setDialog(null)
          }}
        />
      </div>
    </div>
  )
}

function Stat({
  label,
  children
}: {
  label: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className='min-w-0'>
      <dt>
        <Kicker>{label}</Kicker>
      </dt>
      <dd className='m-0'>{children}</dd>
    </div>
  )
}

function CustomRange({
  value,
  min,
  max,
  onChange
}: {
  value: { from: string; to: string } | null
  min: string
  max: string
  onChange: (range: { from: string; to: string }) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<DateRange | undefined>()
  const toDate = (s: string) => {
    const [y, m, d] = s.split('-').map(Number)
    return new Date(y!, (m ?? 1) - 1, d ?? 1)
  }
  const toIso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (o && value)
          setDraft({ from: toDate(value.from), to: toDate(value.to) })
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant='outline'
          aria-label={copy.customRange}
          className='tabular font-sans text-sm font-normal'
        >
          {value ? formatDateRange(value.from, value.to) : copy.customRange}
        </Button>
      </PopoverTrigger>
      <PopoverContent align='start' className='w-auto p-0'>
        <Calendar
          mode='range'
          numberOfMonths={2}
          selected={draft}
          defaultMonth={value ? toDate(value.from) : undefined}
          captionLayout='dropdown'
          disabled={
            min ? [{ before: toDate(min) }, { after: toDate(max) }] : undefined
          }
          onSelect={(r) => {
            setDraft(r)
            if (r?.from && r.to && r.from.getTime() !== r.to.getTime()) {
              onChange({ from: toIso(r.from), to: toIso(r.to) })
              setOpen(false)
            }
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

export function CompanySkeleton({ className }: { className?: string }) {
  return (
    <div
      role='status'
      aria-busy='true'
      className={cn(
        '@container @max-[900px]:grid-cols-1 grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_330px]',
        className
      )}
    >
      <div className='flex min-w-0 flex-col gap-3 p-3.5'>
        <div className='flex gap-5'>
          <SkeletonBar className='w-37.5 h-[22px]' />
          <SkeletonBar className='w-30 h-[22px]' />
        </div>
        <div className='flex gap-5'>
          <SkeletonBar className='w-27.5 h-9' />
          <SkeletonBar className='w-27.5 h-9' />
          <SkeletonBar className='w-27.5 h-9' />
        </div>
        <SkeletonBar className='h-[250px]' />
        <SkeletonBar className='h-[58px]' />
      </div>
      <div className='border-border @max-[900px]:border-t @max-[900px]:border-l-0 flex flex-col gap-2.5 border-l px-3 py-3.5'>
        <SkeletonBar className='h-[26px]' />
        <SkeletonBar className='h-[54px]' />
        <SkeletonBar className='h-[54px]' />
        <SkeletonBar className='h-[54px]' />
      </div>
    </div>
  )
}
