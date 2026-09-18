'use client'

import type { Route } from 'next'
import { usePathname, useRouter } from 'next/navigation'
import { useCallback, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { useCompany } from '@/hooks/useCompany'
import { useMarket } from '@/hooks/useMarket'
import { useStatus } from '@/hooks/useStatus'
import { createStockTickerChat } from '@/lib/chat'
import { primaryListing } from '@/lib/company'
import { companyHref } from '@/lib/routes'

import { AppShell } from '../shell/app-shell'
import type { Screen } from '../shell/app-shell'
import type { PaletteEntry } from '../shell/command-palette'
import { shellCopy } from '../shell/copy'
import { AskContainer } from './ask-container'

function screenOf(pathname: string): Screen {
  if (pathname.startsWith('/companies')) return 'company'
  if (pathname.startsWith('/notes')) return 'notes'
  return 'market'
}

export function ShellContainer({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const status = useStatus()
  const market = useMarket()
  const [askOpen, setAskOpen] = useState(false)
  // One conversation for the whole session: it outlives the Ask panel
  // closing and the switch between docked column and full-screen sheet.
  const [chat] = useState(createStockTickerChat)

  const current = screenOf(pathname)
  const cik =
    current === 'company'
      ? decodeURIComponent(pathname.split('/')[2] ?? '')
      : null
  const [lastCik, setLastCik] = useState<string | null>(cik)
  if (cik && cik !== lastCik) setLastCik(cik)
  const company = useCompany(lastCik ?? undefined)

  const entries: PaletteEntry[] = useMemo(
    () =>
      (market.data?.listings ?? []).map((r) => ({
        cik: r.cik,
        symbol: r.symbol,
        name: r.name,
        price: r.price,
        change_pct: r.change_pct
      })),
    [market.data]
  )

  const crumbs =
    current === 'company'
      ? shellCopy.crumbs.company(company.data?.name ?? shellCopy.nav.company)
      : current === 'notes'
        ? shellCopy.crumbs.notes
        : shellCopy.crumbs.market
  const navigate = useCallback((href: Route) => router.push(href), [router])

  return (
    <AppShell
      current={current}
      crumbs={crumbs}
      status={status.data ?? null}
      ai={status.data?.ai ?? null}
      statusLoading={status.isPending}
      company={
        lastCik
          ? {
              symbol: company.data
                ? (primaryListing(company.data.listings)?.symbol ?? '')
                : '',
              href: companyHref(lastCik)
            }
          : null
      }
      paletteEntries={entries}
      onPaletteSelect={(e) => navigate(companyHref(e.cik))}
      onNavigate={navigate}
      askOpen={askOpen}
      onAskOpenChange={setAskOpen}
      ask={<AskContainer chat={chat} onClose={() => setAskOpen(false)} />}
    >
      {children}
    </AppShell>
  )
}
