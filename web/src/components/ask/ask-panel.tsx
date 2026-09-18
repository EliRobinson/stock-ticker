'use client'

import { ChevronDown, ChevronRight, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ComponentProps } from 'react'

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
import type { TimeseriesViewSpec } from '@/lib/chat'
import { cn } from '@/lib/utils'

import { TimeseriesChart } from '../chart/timeseries-chart'
import { StatusAlert } from '../shared/feedback'
import { toNumber } from '../shared/format'
import { askCopy as copy } from './copy'
import type {
  AskMessage,
  AskStatus,
  AskUnavailable,
  RunSqlInput,
  RunSqlOutput
} from './types'
import { ViewTable } from './view-table'

type Part = AskMessage['parts'][number]
type ToolPart = Extract<Part, { toolCallId: string }>
type ViewPart = Extract<Part, { type: 'data-view' }>

const isTool = (p: Part): p is ToolPart => p.type.startsWith('tool-')
const toolName = (p: ToolPart) => p.type.slice('tool-'.length)

// Markdown in answers: raw HTML off, remote images off, only https links (system design §7).
const safeMarkdown: Partial<ComponentProps<typeof MessageResponse>> = {
  skipHtml: true,
  disallowedElements: ['img'],
  urlTransform: (url: string) => (url.startsWith('https://') ? url : null)
}

export interface AskPanelProps {
  messages: AskMessage[]
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
  messages,
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
  const empty = messages.length === 0

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
            {messages.map((m, i) => (
              <AskTurn
                key={m.id}
                message={m}
                streaming={busy && i === messages.length - 1}
                compact={compact}
                defaultSqlOpen={defaultSqlOpen}
              />
            ))}
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
            className='border-input bg-secondary min-h-13 text-md w-full border px-2.5 py-1.5 opacity-45'
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

function AskTurn({
  message,
  streaming,
  compact,
  defaultSqlOpen
}: {
  message: AskMessage
  streaming: boolean
  compact: boolean
  defaultSqlOpen: boolean
}) {
  if (message.role === 'user') {
    const text = message.parts
      .map((p) => (p.type === 'text' ? p.text : ''))
      .join('')
    return (
      <Message from='user' className='max-w-[88%]'>
        <MessageContent className='group-[.is-user]:border-border group-[.is-user]:bg-secondary text-sm group-[.is-user]:rounded-none group-[.is-user]:border group-[.is-user]:px-2.5 group-[.is-user]:py-2'>
          {text}
        </MessageContent>
      </Message>
    )
  }

  const tools = message.parts.filter(isTool)
  const sqlTools = tools.filter((t) => toolName(t) === 'run_sql')
  const views = message.parts.filter(
    (p): p is ViewPart => p.type === 'data-view'
  )
  const texts = message.parts.filter((p) => p.type === 'text')
  const failed = sqlTools.some((t) => t.state === 'output-error')

  return (
    <Message from='assistant' className='max-w-full gap-2.5'>
      {tools.length > 0 && <ToolSteps tools={tools} />}
      {texts.map((p, i) => (
        <MessageContent key={i} className='text-sm leading-[1.55]'>
          <div aria-busy={streaming || undefined}>
            <MessageResponse {...safeMarkdown}>
              {p.type === 'text' ? p.text : ''}
            </MessageResponse>
            {streaming && i === texts.length - 1 && (
              <span
                aria-hidden='true'
                className='bg-brand animate-caret ml-0.5 inline-block h-3.5 w-[7px] align-[-2px]'
              />
            )}
          </div>
        </MessageContent>
      ))}
      {views.map((v, i) =>
        v.data.kind === 'table' ? (
          <ViewTable key={v.id ?? i} spec={v.data} />
        ) : (
          <TimeseriesChart
            key={v.id ?? i}
            ariaLabel={v.data.title}
            height={compact ? 120 : 150}
            series={v.data.series.map((s) => {
              const spec = v.data as TimeseriesViewSpec
              return {
                label: s.label,
                points: spec.rows
                  .map((r) => ({
                    time: String(r[spec.x]),
                    value: toNumber(r[s.key] as string | number | null)
                  }))
                  .filter(
                    (p): p is { time: string; value: number } => p.value != null
                  )
              }
            })}
          />
        )
      )}
      {sqlTools.length > 0 && !streaming && (
        <SqlDisclosure
          sql={sqlTools.map(
            (t) => (t.input as RunSqlInput | undefined)?.sql ?? ''
          )}
          defaultOpen={failed || defaultSqlOpen}
        />
      )}
      {views.some((v) => v.data.kind === 'table') && (
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

function ToolSteps({ tools }: { tools: ToolPart[] }) {
  return (
    <div
      role='log'
      aria-live='polite'
      aria-label={copy.toolLog}
      className='border-border flex flex-col gap-1 border px-2.5 py-2 text-xs'
    >
      {tools.map((t) => {
        const name = toolName(t)
        const input = t.input as RunSqlInput | undefined
        const done = t.state === 'output-available'
        const failed = t.state === 'output-error'
        const output = done ? (t.output as RunSqlOutput | undefined) : undefined
        const label =
          name === 'run_sql'
            ? `${input?.purpose ?? name}${output?.row_count != null ? ` \u00b7 ${copy.rows(output.row_count, output.row_count_is_capped)}` : ''}`
            : (copy.quietStep[name] ?? name)
        return (
          <Tool key={t.toolCallId} className='mb-0 border-0'>
            <ToolHeader
              type='dynamic-tool'
              toolName={name}
              state={t.state}
              title={label}
              className={cn(
                // AI Elements' header, restyled to the design's step log: the
                // status icon leads, the wrench, badge label and chevron go.
                'justify-start gap-2 p-0 text-left text-xs [&>div>span]:text-xs [&>div>span]:font-normal [&>div>svg:first-child]:hidden [&>svg:last-child]:hidden [&_[data-slot=badge]]:order-first [&_[data-slot=badge]]:border-0 [&_[data-slot=badge]]:bg-transparent [&_[data-slot=badge]]:p-0 [&_[data-slot=badge]]:text-[0px] [&_[data-slot=badge]_svg]:size-3.5',
                (done || name !== 'run_sql') && 'text-muted-foreground',
                failed && 'text-down'
              )}
            />
            {failed && t.errorText && (
              <p className='text-down mt-1 text-xs'>{t.errorText}</p>
            )}
            <ToolContent className='p-0 pt-1.5'>
              {name === 'run_sql' && (
                <ToolInput input={t.input} className='p-0' />
              )}
            </ToolContent>
            <span className='sr-only'>
              {done
                ? copy.stepDone
                : failed
                  ? copy.stepFailed
                  : copy.stepRunning}
            </span>
          </Tool>
        )
      })}
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
  const code = useMemo(() => sql.filter(Boolean).join('\n\n'), [sql])
  if (!code) return null
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
          <CodeBlock
            code={code}
            language='sql'
            className='border-border bg-secondary text-2xs rounded-none border'
          />
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
