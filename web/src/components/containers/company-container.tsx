'use client'

import { useState } from 'react'

import { useBars } from '@/hooks/useBars'
import { useCompany } from '@/hooks/useCompany'
import { useEvents } from '@/hooks/useEvents'
import { useMarket } from '@/hooks/useMarket'
import { createNoteId, useNotes, usePutNote } from '@/hooks/useNotes'

import { CompanyScreen } from '../company/company-screen'
import { noteDialogCopy } from '../company/copy'
import { todayInNewYork } from './today'

const HISTORY_START = '2018-01-02'

// Weekdays from the history start to today: an upper bound on Trading Days,
// used only to size the "History loading" banner while backfill runs.
function expectedTradingDays(today: string) {
  let n = 0
  const end = Date.parse(`${today}T00:00:00Z`)
  for (
    let t = Date.parse(`${HISTORY_START}T00:00:00Z`);
    t <= end;
    t += 86_400_000
  ) {
    const dow = new Date(t).getUTCDay()
    if (dow !== 0 && dow !== 6) n++
  }
  return n
}

export function CompanyContainer({ cik }: { cik: string }) {
  const company = useCompany(cik)
  const market = useMarket()
  const primary =
    company.data?.listings.find((l) => l.is_primary)?.symbol ??
    company.data?.listings[0]?.symbol ??
    ''
  const [picked, setPicked] = useState<string | null>(null)
  const symbol = picked ?? primary
  const bars = useBars(symbol || undefined)
  const events = useEvents({ cik })
  const notes = useNotes({ cik })
  const putNote = usePutNote()
  const today = todayInNewYork()

  const listing = company.data?.listings.find((l) => l.symbol === symbol)
  const quote = market.data?.listings.find((r) => r.symbol === symbol) ?? null
  const loaded = bars.data?.length ?? 0
  const backfill =
    listing && listing.first_bar_date == null && loaded > 0
      ? { loaded, expected: expectedTradingDays(today) }
      : null

  return (
    <CompanyScreen
      company={company.data ?? null}
      loading={company.isPending}
      chartError={company.isError || bars.isError}
      symbol={symbol}
      onSymbolChange={setPicked}
      quote={quote}
      serverTime={market.data?.server_time ?? null}
      isOpen={market.data?.market_clock?.is_open ?? false}
      bars={bars.data ?? null}
      backfill={backfill}
      notes={notes.data?.pages.flatMap((p) => p.items) ?? []}
      events={events.data?.pages.flatMap((p) => p.items) ?? []}
      today={today}
      noteSaveError={putNote.isError ? noteDialogCopy.saveFailed : null}
      onSaveNote={(draft) =>
        putNote.mutate({
          id: draft.id ?? createNoteId(),
          cik: draft.cik,
          start_date: draft.start_date,
          end_date: draft.end_date,
          body: draft.body
        })
      }
    />
  )
}
