'use client'

import { useEffect, useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type {
  Bar,
  CompanyDetail,
  MarketEvent,
  MarketRow,
  Note
} from '@/lib/api'
import {
  eventMarkerId,
  mapBarsToCandlestickSeries,
  mapBarsToVolumeSeries,
  mapEventsToMarkers,
  mapNotesToMarkers
} from '@/lib/chart-data'
import { formatDateShort } from '@/lib/format'
import type { NoteDraft } from '@/hooks/useNotes'
import { HISTORY_START } from '@/lib/dates'
import { companyOption } from '@/lib/company'
import { getQuoteStaleness } from '@/lib/staleness'

import { PriceChart } from '../chart/price-chart'
import { NoteDialog, emptyDraft } from '../notes/note-dialog'
import { TruncatedText } from '../shared/cells'
import { EmptyState, SkeletonBar, StatusAlert } from '../shared/feedback'
import { MarkerLegend } from '../shared/marker-legend'
import { Segmented } from '../shared/segmented'
import { ChartToolbar } from './chart-toolbar'
import type { ChartMode } from './chart-toolbar'
import { CompanyStats } from './company-stats'
import { companyCopy as copy } from './copy'
import { NotesEventsPanel } from './notes-events-panel'
import type { PanelItem, PanelTab } from './notes-events-panel'
import { PRESETS, presetFits, resolveRange, widenToInclude } from './range'
import type { ChartRange } from './range'

const DEFAULT_KINDS = ['splits', '8k']

export interface CompanyView {
  range: ChartRange
  mode: ChartMode
  tab: PanelTab
}

export interface CompanyScreenProps {
  company: CompanyDetail | null
  loading?: boolean
  error?: boolean
  onRetry?: () => void
  symbol: string
  onSymbolChange: (symbol: string) => void
  quote: MarketRow | null
  serverTime: string | null
  isOpen: boolean
  bars: Bar[] | null
  barsError?: boolean
  backfill?: { loaded: number; expected: number } | null
  notes: Note[]
  events: MarketEvent[]
  today: string
  view: CompanyView
  onViewChange: (view: Partial<CompanyView>) => void
  onSaveNote: (draft: NoteDraft) => Promise<unknown>
}

type DialogState = { draft: NoteDraft; origin?: 'range' | 'date' } | null

export function CompanyScreen({
  company,
  loading = false,
  error = false,
  onRetry,
  symbol,
  onSymbolChange,
  quote,
  serverTime,
  isOpen,
  bars,
  barsError = false,
  backfill = null,
  notes,
  events,
  today,
  view,
  onViewChange,
  onSaveNote
}: CompanyScreenProps) {
  const [kinds, setKinds] = useState<string[]>(DEFAULT_KINDS)
  const [highlighted, setHighlighted] = useState<string | null>(null)
  const [dialog, setDialog] = useState<DialogState>(null)

  const candles = useMemo(
    () => (bars ? mapBarsToCandlestickSeries(bars) : []),
    [bars]
  )
  const volume = useMemo(
    () =>
      bars
        ? mapBarsToVolumeSeries(bars).map(({ time, value }) => ({
            time,
            value
          }))
        : [],
    [bars]
  )
  const first = candles[0] ? String(candles[0].time) : ''
  const last = candles.length ? String(candles[candles.length - 1]!.time) : ''

  const enabledKinds = useMemo(
    () =>
      new Set<string>(
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

  const { markers, outsideIds } = useMemo(() => {
    if (!bars || bars.length === 0)
      return { markers: [], outsideIds: new Set<string>() }
    const n = mapNotesToMarkers(notes, bars)
    const e = mapEventsToMarkers(events, bars)
    const shown = new Set(shownEvents.map(eventMarkerId))
    return {
      markers: [...n.markers, ...e.markers.filter((m) => shown.has(m.id))],
      outsideIds: new Set<string>([
        ...n.outsideRange.map((x) => x.id),
        ...e.outsideRange.map(eventMarkerId)
      ])
    }
  }, [bars, notes, events, shownEvents])

  const visible = useMemo(
    () => resolveRange(view.range, first, last),
    [view.range, first, last]
  )
  const chartSummary = useMemo(() => {
    const noteCount = markers.filter((m) => m.kind === 'note').length
    const eventCount = markers.length - noteCount
    const firstClose = candles[0]?.close
    const lastClose = candles[candles.length - 1]?.close
    return `${first} to ${last}, from ${firstClose?.toFixed(2) ?? ''} to ${lastClose?.toFixed(2) ?? ''}. ${noteCount} Notes and ${eventCount} Events marked.`
  }, [markers, candles, first, last])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (
        target?.closest(
          'input, textarea, [contenteditable="true"], [role="dialog"], [role="menu"]'
        )
      )
        return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const preset = PRESETS[Number(e.key) - 1]
      if (preset && (!first || presetFits(preset, first, last))) {
        onViewChange({ range: { kind: 'preset', preset } })
      } else if (e.key.toLowerCase() === 'c') {
        onViewChange({ mode: view.mode === 'line' ? 'candles' : 'line' })
      } else if (e.key.toLowerCase() === 'n' && company) {
        setDialog({ draft: emptyDraft(company.cik, last || today) })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [first, last, today, company, view.mode, onViewChange])

  if (error) {
    return (
      <div className='p-3.5'>
        <StatusAlert
          title={copy.companyErrorTitle}
          action={
            onRetry && (
              <Button
                variant='destructive'
                size='sm'
                onClick={onRetry}
                className='font-sans text-xs font-normal'
              >
                {copy.retry}
              </Button>
            )
          }
        >
          {copy.companyErrorBody}
        </StatusAlert>
      </div>
    )
  }
  if (loading || !company) return <CompanySkeleton />

  const q =
    quote && serverTime
      ? getQuoteStaleness(quote.observed_at, serverTime, isOpen)
      : null
  const partialHistory =
    company.first_bar_date != null && company.first_bar_date > HISTORY_START
  const onKindsLabel = copy.eventToggles
    .filter((t) => kinds.includes(t.id))
    .map((t) => t.label)
  const option = companyOption({ cik: company.cik, symbol, name: company.name })

  const selectItem = (item: PanelItem | null) => {
    setHighlighted(item?.id ?? null)
    if (
      item &&
      visible &&
      (item.start < visible.from || item.end > visible.to)
    ) {
      onViewChange({
        range: widenToInclude(
          visible,
          item.start < first ? first : item.start,
          item.end > last ? last : item.end
        )
      })
    }
  }

  return (
    <div className='@container flex min-h-0 flex-1 flex-col overflow-auto'>
      <div className='@max-stack:grid-cols-1 grid grid-cols-[minmax(0,1fr)_330px]'>
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
            <CompanyStats
              company={company}
              quote={quote}
              quoteAgeMs={q?.ageMs ?? null}
              stale={q?.isStale ?? false}
              isOpen={isOpen}
              lastBar={bars?.[bars.length - 1]}
            />
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

          {barsError ? (
            <div className='p-3.5'>
              <StatusAlert centered title={copy.chartErrorTitle}>
                <span className='text-sm'>{copy.chartErrorBody}</span>
              </StatusAlert>
            </div>
          ) : bars && bars.length === 0 ? (
            <EmptyState
              className='min-h-[308px]'
              title={copy.noBarsTitle(symbol)}
              body={copy.noBarsBody}
            />
          ) : (
            <>
              <ChartToolbar
                range={view.range}
                visible={visible}
                first={first}
                last={last}
                onRangeChange={(range) => onViewChange({ range })}
                mode={view.mode}
                onModeChange={(mode) => onViewChange({ mode })}
                kinds={kinds}
                onKindsChange={setKinds}
              />
              <div className='px-3.5 pb-3.5'>
                {bars ? (
                  <PriceChart
                    candles={candles}
                    volume={volume}
                    mode={view.mode}
                    markers={markers}
                    highlightedId={highlighted}
                    visibleRange={visible}
                    onSelect={(start, end) =>
                      setDialog({
                        draft: {
                          ...emptyDraft(company.cik, start),
                          end_date: end
                        },
                        origin: start === end ? 'date' : 'range'
                      })
                    }
                    ariaLabel={copy.chartAria(company.name, view.mode)}
                    summary={chartSummary}
                  />
                ) : (
                  <SkeletonBar className='h-[308px]' />
                )}
                {partialHistory && (
                  <p className='text-muted-foreground mt-2 text-xs'>
                    {copy.historyStarts(
                      formatDateShort(company.first_bar_date)
                    )}
                  </p>
                )}
                <MarkerLegend
                  note={copy.legendNote}
                  event={copy.legendEvent}
                  hint={
                    view.mode === 'candles'
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
          outsideIds={outsideIds}
          highlightedId={highlighted}
          onSelectItem={selectItem}
          onNewNote={() =>
            setDialog({ draft: emptyDraft(company.cik, last || today) })
          }
          tab={view.tab}
          onTabChange={(tab) => onViewChange({ tab })}
        />
      </div>

      <NoteDialog
        open={dialog != null}
        onOpenChange={(open) => !open && setDialog(null)}
        initial={dialog?.draft ?? emptyDraft(company.cik, last || today)}
        companies={[option]}
        lockCompany
        origin={dialog?.origin}
        today={today}
        onSave={onSaveNote}
      />
    </div>
  )
}

export function CompanySkeleton() {
  return (
    <div role='status' aria-busy='true' className='@container min-h-0 flex-1'>
      <div className='@max-stack:grid-cols-1 grid grid-cols-[minmax(0,1fr)_330px]'>
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
        <div className='border-border @max-stack:border-t @max-stack:border-l-0 flex flex-col gap-2.5 border-l px-3 py-3.5'>
          <SkeletonBar className='h-[26px]' />
          <SkeletonBar className='h-[54px]' />
          <SkeletonBar className='h-[54px]' />
          <SkeletonBar className='h-[54px]' />
        </div>
      </div>
    </div>
  )
}
