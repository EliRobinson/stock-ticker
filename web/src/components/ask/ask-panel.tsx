'use client'

import { ChevronDown, ChevronRight, X } from 'lucide-react'
import { useMemo, useState, useSyncExternalStore } from 'react'

import { CodeBlock } from '@/components/ai-elements/code-block'
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton
} from '@/components/ai-elements/conversation'
import {
  Message,
  MessageContent,
  MessageResponse
} from '@/components/ai-elements/message'
import {
  PromptInput,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea
} from '@/components/ai-elements/prompt-input'
import { Suggestion } from '@/components/ai-elements/suggestion'
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput
} from '@/components/ai-elements/tool'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

import { TimeseriesChart } from '../chart/timeseries-chart'
import { RegionBoundary } from '../shared/error-boundary'
import { StatusAlert } from '../shared/feedback'
import { safeMarkdownProps } from '../shared/markdown'
import { askCopy as copy } from './copy'
import type { AskTurnModel, StepState, ToolStep, ViewModel } from './prepare'
import type { AskStatus, AskUnavailable } from './types'
import { ViewTable } from './view-table'

const noopSubscribe = () => () => {}

// AI Elements' Tool takes the AI SDK's part states; the panel's own
// StepState maps onto them for the status icon.
const TOOL_STATE: Record<
  StepState,
  'input-available' | 'output-available' | 'output-error' | 'output-denied'
> = {
  running: 'input-available',
  done: 'output-available',
  failed: 'output-error',
  stopped: 'output-denied'
}

export interface AskPanelProps {
  turns: AskTurnModel[]
  status: AskStatus
  error?: string | null
  unavailable?: AskUnavailable
  spendLimit?: string
  onSend: (text: string) => void
  onRetry?: () => void
  onStop?: () => void
  onClose?: () => void
  compact?: boolean
  defaultSqlOpen?: boolean
  className?: string
}

export function AskPanel({
  turns,
  status,
  error = null,
  unavailable = null,
  spendLimit,
  onSend,
  onRetry,
  onStop,
  onClose,
  compact = false,
  defaultSqlOpen = false,
  className
}: AskPanelProps) {
  const [draft, setDraft] = useState('')
  const busy = status === 'submitted' || status === 'streaming'
  const empty = turns.length === 0

  return (
    <section
      aria-label={copy.title}
      className={cn('bg-background flex h-full min-h-0 flex-col', className)}
    >
      <div className='border-border flex items-center gap-2 border-b px-3.5 py-3'>
        <span aria-hidden='true' className='bg-brand block h-4 w-1' />
        <h2 className='m-0 text-xl'>{copy.title}</h2>
        <span className='text-muted-foreground text-2xs ml-1.5'>
          {busy ? copy.working : copy.subtitle}
        </span>
        {onClose && (
          <Button
            variant='outline'
            size='icon'
            aria-label={copy.close}
            onClick={onClose}
            className='touch:size-11 ml-auto'
          >
            <X aria-hidden='true' strokeWidth={1.5} />
          </Button>
        )}
      </div>

      {unavailable && empty ? (
        <UnavailableNotice unavailable={unavailable} spendLimit={spendLimit} />
      ) : empty ? (
        <div className='flex flex-1 flex-col gap-2 overflow-auto p-3.5'>
          <p className='text-muted-foreground mb-0.5 text-xs'>{copy.intro}</p>
          {copy.suggestions.map((s) => (
            <Suggestion
              key={s}
              suggestion={s}
              onClick={(text) => onSend(text)}
              disabled={unavailable != null}
              variant='outline'
              className='touch:min-h-12 h-auto justify-start whitespace-normal px-2.5 py-2 text-left font-sans text-xs font-normal'
            />
          ))}
        </div>
      ) : (
        <Conversation className='min-h-0'>
          <ConversationContent className='gap-3 p-3.5'>
            {turns.map((turn) =>
              turn.role === 'user' ? (
                <Message key={turn.id} from='user' className='max-w-[88%]'>
                  <MessageContent className='group-[.is-user]:border-border group-[.is-user]:bg-secondary text-sm group-[.is-user]:rounded-none group-[.is-user]:border group-[.is-user]:px-2.5 group-[.is-user]:py-2'>
                    {turn.text}
                  </MessageContent>
                </Message>
              ) : (
                <AssistantTurn
                  key={turn.id}
                  turn={turn}
                  compact={compact}
                  defaultSqlOpen={defaultSqlOpen}
                />
              )
            )}
            {error && (
              <div
                role='alert'
                className='border-pill-bad-foreground bg-pill-bad text-pill-bad-foreground flex flex-col items-start gap-2 text-pretty border px-3 py-2.5 text-sm'
              >
                <span>{error}</span>
                {onRetry && (
                  <Button
                    variant='destructive'
                    size='sm'
                    onClick={onRetry}
                    className='font-sans text-xs font-normal'
                  >
                    {copy.retry}
                  </Button>
                )}
              </div>
            )}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>
      )}

      {unavailable ? (
        <div className='border-border mt-auto flex flex-col gap-2.5 border-t p-3'>
          {!empty && (
            <UnavailableNotice
              unavailable={unavailable}
              spendLimit={spendLimit}
              inline
            />
          )}
          <textarea
            disabled
            aria-label={copy.inputLabel}
            placeholder={copy.placeholderDisabled}
            className='border-input bg-secondary text-md min-h-13 w-full border px-2.5 py-1.5 opacity-45'
          />
        </div>
      ) : (
        <PromptInput
          onSubmit={(message) => {
            const text = message.text.trim()
            if (!text || busy) return
            onSend(text)
            setDraft('')
          }}
          className='border-border [&_[data-slot=input-group]]:border-input [&_[data-slot=input-group]]:bg-secondary mt-auto border-t p-3 [&_[data-slot=input-group]]:rounded-none [&_[data-slot=input-group]]:shadow-none'
        >
          <PromptInputTextarea
            aria-label={copy.inputLabel}
            placeholder={copy.placeholder}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className='text-md min-h-14'
          />
          <PromptInputFooter className='justify-between'>
            <span className='text-muted-foreground text-2xs px-1'>
              {copy.hint}
            </span>
            <PromptInputSubmit
              status={status}
              onStop={onStop}
              size='sm'
              aria-label={busy ? copy.stop : copy.send}
              className='touch:min-h-11 px-3'
            >
              {busy ? copy.stop : copy.send}
            </PromptInputSubmit>
          </PromptInputFooter>
        </PromptInput>
      )}
      <p className='text-muted-foreground text-2xs text-pretty px-3 pb-2.5'>
        {copy.disclosure}
      </p>
    </section>
  )
}

function UnavailableNotice({
  unavailable,
  spendLimit,
  inline = false
}: {
  unavailable: Exclude<AskUnavailable, null>
  spendLimit?: string
  inline?: boolean
}) {
  const alert =
    unavailable === 'missing-key' ? (
      <StatusAlert title={copy.missingKeyTitle} icon={false}>
        {copy.missingKeyBody}
      </StatusAlert>
    ) : (
      <StatusAlert title={copy.spendTitle} icon={false}>
        {copy.spendBody(spendLimit ?? '$5.00')}
      </StatusAlert>
    )
  if (inline) return alert
  return (
    <div className='flex flex-col gap-2.5 p-3.5'>
      {alert}
      <p className='text-muted-foreground text-xs'>{copy.otherScreensWork}</p>
    </div>
  )
}

function AssistantTurn({
  turn,
  compact,
  defaultSqlOpen
}: {
  turn: Extract<AskTurnModel, { role: 'assistant' }>
  compact: boolean
  defaultSqlOpen: boolean
}) {
  const sql = turn.steps.filter((s) => s.sql).map((s) => s.sql!)
  const failed = turn.steps.some((s) => s.state === 'failed')
  return (
    <Message from='assistant' className='max-w-full gap-2.5'>
      {turn.steps.length > 0 && <ToolSteps steps={turn.steps} />}
      {turn.texts.map((text, i) => (
        <MessageContent key={i} className='text-sm leading-[1.55]'>
          <div aria-busy={turn.streaming || undefined}>
            <MessageResponse {...safeMarkdownProps}>{text}</MessageResponse>
            {turn.streaming && i === turn.texts.length - 1 && (
              <span
                aria-hidden='true'
                className='bg-brand animate-caret ml-0.5 inline-block h-3.5 w-[7px] align-[-2px]'
              />
            )}
          </div>
        </MessageContent>
      ))}
      {turn.views.map((view) => (
        <RegionBoundary key={view.id} fallback={<ViewFailed />}>
          <View view={view} compact={compact} />
        </RegionBoundary>
      ))}
      {sql.length > 0 && !turn.streaming && (
        <SqlDisclosure sql={sql} defaultOpen={failed || defaultSqlOpen} />
      )}
      {turn.views.some((v) => v.kind === 'table') && (
        <div className='flex items-center gap-2'>
          <Button
            variant='outline'
            size='sm'
            disabled
            aria-disabled='true'
            className='font-sans text-xs font-normal'
          >
            {copy.pin}
          </Button>
          <span className='text-muted-foreground text-2xs'>
            {copy.pinLater}
          </span>
        </div>
      )}
    </Message>
  )
}

function ViewFailed() {
  return (
    <p
      role='note'
      className='border-border text-muted-foreground border px-2.5 py-2 text-xs'
    >
      {copy.viewFailed}
    </p>
  )
}

function View({ view, compact }: { view: ViewModel; compact: boolean }) {
  if (view.kind === 'invalid') return <ViewFailed />
  if (view.kind === 'table') return <ViewTable spec={view.spec} />
  return (
    <TimeseriesChart
      ariaLabel={view.title}
      height={compact ? 120 : 150}
      series={view.series}
    />
  )
}

function stepLabel(step: ToolStep) {
  if (step.name !== 'run_sql') return copy.quietStep[step.name] ?? step.name
  const rows =
    step.rowCount !== null ? ` · ${copy.rows(step.rowCount, step.capped)}` : ''
  const stopped = step.state === 'stopped' ? ` · ${copy.stopped}` : ''
  return `${step.purpose ?? step.name}${rows}${stopped}`
}

function ToolSteps({ steps }: { steps: ToolStep[] }) {
  return (
    <div
      role='log'
      aria-live='polite'
      aria-label={copy.toolLog}
      className='border-border flex flex-col gap-1 border px-2.5 py-2 text-xs'
    >
      {steps.map((step) => (
        <Tool key={step.id} className='mb-0 border-0'>
          <ToolHeader
            type='dynamic-tool'
            toolName={step.name}
            state={TOOL_STATE[step.state]}
            title={stepLabel(step)}
            className={cn(
              // AI Elements' header, restyled to the design's step log: the
              // status icon leads, the wrench, badge label and chevron go.
              'justify-start gap-2 p-0 text-left text-xs [&>div>span]:text-xs [&>div>span]:font-normal [&>div>svg:first-child]:hidden [&>svg:last-child]:hidden [&_[data-slot=badge]]:order-first [&_[data-slot=badge]]:border-0 [&_[data-slot=badge]]:bg-transparent [&_[data-slot=badge]]:p-0 [&_[data-slot=badge]]:text-[0px] [&_[data-slot=badge]_svg]:size-3.5',
              step.state !== 'running' && 'text-muted-foreground',
              step.state === 'failed' && 'text-down'
            )}
          />
          {step.error && <p className='text-down mt-1 text-xs'>{step.error}</p>}
          <ToolContent className='p-0 pt-1.5'>
            {step.sql && (
              <ToolInput
                input={{ sql: step.sql, purpose: step.purpose }}
                className='p-0'
              />
            )}
          </ToolContent>
          <span className='sr-only'>{copy.stepState[step.state]}</span>
        </Tool>
      ))}
    </div>
  )
}

function SqlDisclosure({
  sql,
  defaultOpen
}: {
  sql: string[]
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  // Shiki highlights on the client only; plain SQL until mount keeps an
  // open-by-default disclosure from mismatching on hydration.
  const mounted = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  )
  const code = useMemo(() => sql.join('\n\n'), [sql])
  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className='flex flex-col gap-2'
    >
      <CollapsibleTrigger asChild>
        <Button
          variant='outline'
          size='sm'
          className='touch:min-h-11 self-start font-sans text-xs font-normal'
        >
          {open ? (
            <ChevronDown
              aria-hidden='true'
              className='size-3.5'
              strokeWidth={1.8}
            />
          ) : (
            <ChevronRight
              aria-hidden='true'
              className='size-3.5'
              strokeWidth={1.8}
            />
          )}
          {open ? copy.hideSql : copy.showSql}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div
          tabIndex={0}
          className='focus-visible:outline-ring focus-visible:outline-2'
        >
          {mounted ? (
            <CodeBlock
              code={code}
              language='sql'
              className='border-border bg-secondary [&_code]:text-2xs [&_pre]:bg-transparent! rounded-none border [&_pre]:p-2.5'
            />
          ) : (
            <pre className='border-border bg-secondary text-2xs m-0 overflow-x-auto border p-2.5 font-mono'>
              {code}
            </pre>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
