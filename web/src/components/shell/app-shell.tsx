'use client'

import {
  ChartLine,
  FileText,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  TrendingUp
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import type { Route } from 'next'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'
import type { StatusResponse } from '@/lib/api'
import { cn } from '@/lib/utils'

import { TOUCH_PHONE, useMediaQuery } from '../shared/use-media'
import { CommandPalette } from './command-palette'
import type { PaletteEntry } from './command-palette'
import { shellCopy as copy } from './copy'
import { StatusStrip } from './status-strip'
import type { AiStatus } from './status-strip'
import { ThemeMenu } from './theme-menu'

export type Screen = 'market' | 'company' | 'notes'

export interface AppShellProps {
  className?: string
  initialCollapsed?: boolean
  children: ReactNode
  current: Screen
  crumbs: readonly string[]
  status: StatusResponse | null
  ai?: AiStatus | null
  statusLoading?: boolean
  company: { symbol: string; href: string } | null
  notesCount?: number
  paletteEntries: PaletteEntry[]
  onPaletteSelect: (entry: PaletteEntry) => void
  ask: ReactNode
  askOpen: boolean
  onAskOpenChange: (open: boolean) => void
}

interface NavEntry {
  id: Screen | 'ask'
  label: string
  icon: LucideIcon
  href?: string
  hint?: string
  disabled?: boolean
}

export function AppShell({
  children,
  current,
  crumbs,
  status,
  ai = null,
  statusLoading = false,
  company,
  notesCount,
  paletteEntries,
  onPaletteSelect,
  ask,
  askOpen,
  onAskOpenChange,
  initialCollapsed,
  className
}: AppShellProps) {
  const router = useRouter()
  const desk = useMediaQuery('(min-width: 1200px)', true)
  const docked = useMediaQuery('(min-width: 900px)', true)
  const touch = useMediaQuery(TOUCH_PHONE)
  const [userCollapsed, setUserCollapsed] = useState<boolean | null>(
    initialCollapsed ?? null
  )
  const [paletteOpen, setPaletteOpen] = useState(false)
  const collapsed = userCollapsed ?? !desk

  const nav: NavEntry[] = [
    { id: 'market', label: copy.nav.market, icon: TrendingUp, href: '/' },
    {
      id: 'company',
      label: copy.nav.company,
      icon: ChartLine,
      href: company?.href,
      hint: company?.symbol,
      disabled: !company
    },
    {
      id: 'notes',
      label: copy.nav.notes,
      icon: FileText,
      href: '/notes',
      hint: notesCount != null ? String(notesCount) : undefined
    },
    { id: 'ask', label: copy.nav.ask, icon: MessageSquare, hint: '⌥A' }
  ]

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((o) => !o)
      } else if (e.altKey && e.code === 'KeyA') {
        e.preventDefault()
        onAskOpenChange(!askOpen)
      } else if (mod && e.key === '1') {
        e.preventDefault()
        router.push('/')
      } else if (mod && e.key === '2' && company) {
        e.preventDefault()
        router.push(company.href as Route)
      } else if (mod && e.key === '3') {
        e.preventDefault()
        router.push('/notes')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [askOpen, onAskOpenChange, router, company])

  const sidebarWidth = touch ? 0 : collapsed ? (docked ? 60 : 48) : 212
  const askWidth = desk ? 420 : 380
  const showDocked = askOpen && docked

  return (
    <div
      className={cn(
        'bg-background text-foreground grid h-dvh overflow-hidden',
        className
      )}
      style={{
        gridTemplateColumns: `${sidebarWidth}px minmax(0,1fr) ${showDocked ? askWidth : 0}px`,
        gridTemplateRows: `${docked ? 52 : 44}px minmax(0,1fr)`
      }}
    >
      <header className='border-border col-span-3 flex items-center gap-4 border-b px-4 max-md:gap-2 max-md:px-2.5'>
        <span className='font-heading text-lg uppercase tracking-[0.02em] max-md:hidden'>
          {copy.brand}
        </span>
        <nav
          aria-label={copy.breadcrumb}
          className='text-muted-foreground flex min-w-0 items-center gap-2 text-sm'
        >
          {crumbs.map((c, i) => (
            <span key={`${c}-${i}`} className='flex min-w-0 items-center gap-2'>
              {i > 0 && (
                <span aria-hidden='true' className='opacity-70'>
                  /
                </span>
              )}
              <span
                className={cn(
                  'truncate',
                  i === crumbs.length - 1 && 'text-foreground',
                  i < crumbs.length - 1 && 'max-md:hidden'
                )}
                aria-current={i === crumbs.length - 1 ? 'page' : undefined}
              >
                {c}
              </span>
            </span>
          ))}
        </nav>
        <div className='ml-auto flex items-center gap-2'>
          <Button
            variant='outline'
            onClick={() => setPaletteOpen(true)}
            className='text-muted-foreground min-w-[206px] justify-between gap-2.5 font-sans text-sm font-normal max-md:min-w-0 max-md:px-2'
          >
            <span className='max-md:sr-only'>{copy.jump}</span>
            <kbd className='border-border text-2xs border px-[5px] py-px font-sans'>
              {'⌘K'}
            </kbd>
          </Button>
          <ThemeMenu />
          <Button
            variant={askOpen ? 'default' : 'outline'}
            aria-pressed={askOpen}
            onClick={() => onAskOpenChange(!askOpen)}
            className='gap-1.5 font-sans text-sm font-normal'
          >
            <MessageSquare
              aria-hidden='true'
              className='size-[15px]'
              strokeWidth={1.5}
            />
            <span className='max-md:sr-only'>{copy.nav.ask}</span>
          </Button>
        </div>
      </header>

      <nav
        aria-label={copy.primaryNav}
        className={cn(
          'border-border touch:hidden flex flex-col gap-0.5 border-r py-3',
          collapsed ? 'items-center gap-1 px-1.5' : 'px-2'
        )}
      >
        {nav.map((item) => (
          <NavItem
            key={item.id}
            item={item}
            active={item.id === current || (item.id === 'ask' && askOpen)}
            collapsed={collapsed}
            onAsk={() => onAskOpenChange(!askOpen)}
          />
        ))}
        <div
          className={cn(
            'border-border mt-auto flex flex-col gap-2 border-t pt-2.5',
            collapsed && 'items-center'
          )}
        >
          {!collapsed && (
            <p className='text-muted-foreground text-2xs px-2.5'>
              {copy.footer[0]}
              <br />
              {copy.footer[1]}
            </p>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant='ghost'
                size='icon'
                aria-label={collapsed ? copy.expand : copy.collapse}
                onClick={() => setUserCollapsed(!collapsed)}
                className='text-muted-foreground size-10 px-0 max-md:hidden'
              >
                {collapsed ? (
                  <PanelLeftOpen aria-hidden='true' strokeWidth={1.5} />
                ) : (
                  <PanelLeftClose aria-hidden='true' strokeWidth={1.5} />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='right'>
              {collapsed ? copy.expand : copy.collapse}
            </TooltipContent>
          </Tooltip>
        </div>
      </nav>

      <main className='touch:pb-16 flex min-h-0 min-w-0 flex-col'>
        <StatusStrip status={status} ai={ai} loading={statusLoading} />
        <div className='flex min-h-0 flex-1 flex-col'>{children}</div>
      </main>

      {docked && (
        <aside
          aria-label={copy.nav.ask}
          hidden={!askOpen}
          className='border-border bg-background flex min-h-0 min-w-0 flex-col border-l'
        >
          {ask}
        </aside>
      )}

      {!docked && (
        <Sheet open={askOpen} onOpenChange={onAskOpenChange}>
          <SheetContent
            side='right'
            showCloseButton={false}
            className='w-full gap-0 p-0 sm:max-w-full'
          >
            <SheetTitle className='sr-only'>{copy.nav.ask}</SheetTitle>
            {ask}
          </SheetContent>
        </Sheet>
      )}

      <nav
        aria-label={copy.primaryNav}
        className='border-border bg-background touch:grid fixed inset-x-0 bottom-0 z-40 hidden grid-cols-4 border-t pb-2.5'
      >
        {nav.map((item) => {
          const Icon = item.icon
          const active = item.id === current || (item.id === 'ask' && askOpen)
          const cls = cn(
            'flex min-h-14 flex-col items-center gap-1 border-t-2 border-transparent pt-2 text-2xs',
            active ? 'border-brand text-brand-strong' : 'text-muted-foreground'
          )
          const inner = (
            <>
              <Icon
                aria-hidden='true'
                className='size-[18px]'
                strokeWidth={1.5}
              />
              {item.label}
            </>
          )
          if (item.id === 'ask') {
            return (
              <button
                key={item.id}
                type='button'
                className={cls}
                onClick={() => onAskOpenChange(!askOpen)}
              >
                {inner}
              </button>
            )
          }
          if (!item.href) {
            return (
              <span
                key={item.id}
                aria-disabled='true'
                className={cn(cls, 'opacity-45')}
              >
                {inner}
              </span>
            )
          }
          return (
            <Link
              key={item.id}
              href={item.href as Route}
              className={cls}
              aria-current={active ? 'page' : undefined}
            >
              {inner}
            </Link>
          )
        })}
      </nav>

      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        entries={paletteEntries}
        onSelect={(entry) => {
          setPaletteOpen(false)
          onPaletteSelect(entry)
        }}
      />
    </div>
  )
}

function NavItem({
  item,
  active,
  collapsed,
  onAsk
}: {
  item: NavEntry
  active: boolean
  collapsed: boolean
  onAsk: () => void
}) {
  const Icon = item.icon
  const cls = cn(
    'flex items-center border-transparent text-md transition-colors hover:bg-foreground/7 focus-visible:outline-ring focus-visible:outline-2 focus-visible:outline-offset-2',
    collapsed
      ? 'size-10 justify-center border max-md:size-9'
      : 'min-h-11 gap-2.5 border-l-2 px-2.5 py-[9px]',
    active && 'bg-sidebar-accent text-sidebar-accent-foreground',
    active &&
      (collapsed ? 'border-sidebar-primary' : 'border-l-sidebar-primary'),
    item.disabled &&
      'text-muted-foreground cursor-not-allowed hover:bg-transparent'
  )
  const content = (
    <>
      <Icon aria-hidden='true' className='size-4 flex-none' strokeWidth={1.5} />
      {collapsed ? (
        <span className='sr-only'>{item.label}</span>
      ) : (
        <>
          <span>{item.label}</span>
          {item.hint && (
            <span className='text-muted-foreground text-2xs tabular ml-auto'>
              {item.hint}
            </span>
          )}
        </>
      )}
    </>
  )

  let control: ReactNode
  if (item.id === 'ask') {
    control = (
      <button
        type='button'
        aria-pressed={active}
        onClick={onAsk}
        className={cls}
      >
        {content}
      </button>
    )
  } else if (item.disabled || !item.href) {
    control = (
      <span role='link' tabIndex={0} aria-disabled='true' className={cls}>
        {content}
      </span>
    )
  } else {
    control = (
      <Link
        href={item.href as Route}
        aria-current={active ? 'page' : undefined}
        className={cls}
      >
        {content}
      </Link>
    )
  }

  const tip = item.disabled
    ? copy.companyDisabled
    : collapsed
      ? item.label
      : null
  if (!tip) return control
  return (
    <Tooltip>
      <TooltipTrigger asChild>{control}</TooltipTrigger>
      <TooltipContent side='right'>{tip}</TooltipContent>
    </Tooltip>
  )
}
