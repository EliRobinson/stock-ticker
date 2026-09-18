'use client'

import type { Route } from 'next'
import { usePathname, useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { useMarket } from '@/hooks/useMarket'
import { useNotes } from '@/hooks/useNotes'
import { useStatus } from '@/hooks/useStatus'

import { AppShell } from '../shell/app-shell'
import type { Screen } from '../shell/app-shell'
import type { PaletteEntry } from '../shell/command-palette'
import { shellCopy } from '../shell/copy'
import { AskContainer, readAiStatus } from './ask-container'

export function companyHref(cik: string): Route {
  return `/companies/${cik}` as Route
}

export function ShellContainer({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const status = useStatus()
  const market = useMarket()
  const notes = useNotes()
  const [askOpen, setAskOpen] = useState(false)

  const current: Screen = pathname.startsWith('/companies')
    ? 'company'
    : pathname.startsWith('/notes')
      ? 'notes'
      : 'market'
  const cik =
    current === 'company'
      ? decodeURIComponent(pathname.split('/')[2] ?? '')
      : null
  const [lastCik, setLastCik] = useState<string | null>(cik)
  if (cik && cik !== lastCik) setLastCik(cik)

  const listings = useMemo(() => market.data?.listings ?? [], [market.data])
  const entries: PaletteEntry[] = useMemo(
    () =>
      listings.map((r) => ({
        cik: r.cik,
        symbol: r.symbol,
        name: r.name,
        price: r.price,
        change_pct: r.change_pct
      })),
    [listings]
  )
  const selected = listings.find((r) => r.cik === (cik ?? lastCik))

  const crumbs =
    current === 'company'
      ? shellCopy.crumbs.company(selected?.name ?? shellCopy.nav.company)
      : current === 'notes'
        ? shellCopy.crumbs.notes
        : shellCopy.crumbs.market
  const notesCount = notes.data?.pages.reduce((n, p) => n + p.items.length, 0)

  return (
    <AppShell
      current={current}
      crumbs={crumbs}
      status={status.data ?? null}
      ai={readAiStatus(status.data)}
      statusLoading={status.isPending}
      company={
        lastCik
          ? { symbol: selected?.symbol ?? '', href: companyHref(lastCik) }
          : null
      }
      notesCount={notesCount}
      paletteEntries={entries}
      onPaletteSelect={(e) => router.push(companyHref(e.cik))}
      askOpen={askOpen}
      onAskOpenChange={setAskOpen}
      ask={<AskContainer onClose={() => setAskOpen(false)} />}
    >
      {children}
    </AppShell>
  )
}
