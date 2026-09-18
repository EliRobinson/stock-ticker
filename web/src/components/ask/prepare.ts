import { parseViewSpec } from '@/lib/chat'
import type { ChatUIMessage, TableViewSpec } from '@/lib/chat'
import { toNumber } from '@/lib/format'

import type { TimeseriesSeries } from '../chart/timeseries-chart'
import type { AskStatus, RunSqlInput, RunSqlOutput } from './types'

export type StepState = 'running' | 'done' | 'failed' | 'stopped'

export interface ToolStep {
  id: string
  name: string
  purpose: string | null
  sql: string | null
  state: StepState
  rowCount: number | null
  capped: boolean
  error: string | null
}

export type ViewModel =
  | { id: string; kind: 'table'; spec: TableViewSpec }
  | {
      id: string
      kind: 'timeseries'
      title: string
      series: TimeseriesSeries[]
    }
  | { id: string; kind: 'invalid' }

export type AskTurnModel =
  | { id: string; role: 'user'; text: string }
  | {
      id: string
      role: 'assistant'
      streaming: boolean
      steps: ToolStep[]
      texts: string[]
      views: ViewModel[]
    }

type Part = ChatUIMessage['parts'][number]

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}/

// A time-series chart needs one ascending point per date: lightweight-charts
// throws on unsorted or repeated times. Timestamps are cut to their date.
export function toSeries(spec: {
  x: string
  series: { key: string; label: string }[]
  rows: Record<string, unknown>[]
}): TimeseriesSeries[] {
  return spec.series.map((s) => {
    const byDate = new Map<string, number>()
    for (const row of spec.rows) {
      const x = String(row[spec.x] ?? '').match(DATE_ONLY)?.[0]
      const value = toNumber(row[s.key] as string | number | null)
      if (x && value !== null) byDate.set(x, value)
    }
    const points = [...byDate.entries()]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([time, value]) => ({ time, value }))
    return { label: s.label, points }
  })
}

function toView(
  part: Extract<Part, { type: 'data-view' }>,
  index: number
): ViewModel {
  const id = part.id ?? `view-${index}`
  const parsed = parseViewSpec(part.data)
  if (!parsed.success) return { id, kind: 'invalid' }
  const spec = parsed.data
  if (spec.kind === 'table') return { id, kind: 'table', spec }
  const series = toSeries(spec)
  if (series.every((s) => s.points.length === 0)) return { id, kind: 'invalid' }
  return { id, kind: 'timeseries', title: spec.title, series }
}

function toStep(
  part: Part & { toolCallId: string; state: string },
  finished: boolean
): ToolStep {
  const name =
    part.type === 'dynamic-tool'
      ? (part as { toolName: string }).toolName
      : part.type.slice('tool-'.length)
  const input = ('input' in part ? part.input : undefined) as
    Partial<RunSqlInput> | undefined
  const output = ('output' in part ? part.output : undefined) as
    Partial<RunSqlOutput> | undefined
  const state: StepState =
    part.state === 'output-available'
      ? 'done'
      : part.state === 'output-error'
        ? 'failed'
        : finished
          ? 'stopped'
          : 'running'
  return {
    id: part.toolCallId,
    name,
    purpose: input?.purpose ?? null,
    sql: input?.sql ?? null,
    state,
    rowCount: typeof output?.row_count === 'number' ? output.row_count : null,
    capped: Boolean(output?.row_count_is_capped),
    error:
      'errorText' in part && typeof part.errorText === 'string'
        ? part.errorText
        : null
  }
}

// The stream is untrusted input: every data-view is validated before it
// reaches a renderer, and a tool call that never finished shows as stopped
// once the answer has ended.
export function prepareTurns(
  messages: ChatUIMessage[],
  status: AskStatus
): AskTurnModel[] {
  const busy = status === 'submitted' || status === 'streaming'
  return messages.map((m, i) => {
    if (m.role === 'user') {
      const text = m.parts
        .map((p) => (p.type === 'text' ? p.text : ''))
        .join('')
      return { id: m.id, role: 'user', text }
    }
    const streaming = busy && i === messages.length - 1
    const steps: ToolStep[] = []
    const texts: string[] = []
    const views: ViewModel[] = []
    m.parts.forEach((p, index) => {
      if (p.type === 'text') texts.push(p.text)
      else if (p.type === 'data-view') views.push(toView(p, index))
      else if (
        'toolCallId' in p &&
        (p.type.startsWith('tool-') || p.type === 'dynamic-tool')
      ) {
        steps.push(
          toStep(p as Part & { toolCallId: string; state: string }, !streaming)
        )
      }
    })
    return { id: m.id, role: 'assistant', streaming, steps, texts, views }
  })
}
