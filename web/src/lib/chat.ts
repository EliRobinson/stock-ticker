import { Chat, useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { UIMessage, UIMessagePart } from 'ai'
import { z } from 'zod'
import { env } from '@/env'
import type { components } from './api-types'

/** Created once, not per render/per hook call - a fresh transport instance
 * on every render is wasted work and has no reason to differ between
 * callers, since every chat surface hits the same endpoint. */
const chatTransport = new DefaultChatTransport({
  api: `${env.NEXT_PUBLIC_API_URL}/api/v1/chat`
})

/**
 * `/api/v1/chat`'s response documents `DataViewPart` (system-design.md
 * §6, "View specs") in api/openapi.json, so these are in the generated
 * api-types.ts like any other route's schema - `TableColumn.format` and
 * `TimeseriesChartSpec.y_format` are typed as `string | null` there
 * because the OpenAPI schema doesn't carry Python's `ValueFormat` Literal,
 * so that's what gets validated here too; an unrecognized format string
 * just falls through to `cellText`'s default case (view-table.tsx) rather
 * than failing this parse.
 */
type GeneratedTableColumn = components['schemas']['TableColumn']
type GeneratedChartSeries = components['schemas']['ChartSeries']
type GeneratedTableSpec = components['schemas']['TableSpec']
type GeneratedTimeseriesChartSpec = components['schemas']['TimeseriesChartSpec']

// `satisfies`, not a `: z.ZodType<...>` annotation - the latter would widen
// each const to the abstract ZodType interface and lose the concrete
// ZodObject shape (its `.shape`) that `z.discriminatedUnion` below needs,
// while `satisfies` still fails the build the moment a schema here stops
// matching the generated OpenAPI type.
const viewColumnSchema = z.object({
  key: z.string(),
  label: z.string(),
  format: z.string().nullable().optional()
}) satisfies z.ZodType<GeneratedTableColumn>

const tableViewSpecSchema = z.object({
  kind: z.literal('table'),
  id: z.string(),
  title: z.string(),
  columns: z.array(viewColumnSchema),
  rows: z.array(z.record(z.string(), z.unknown()))
}) satisfies z.ZodType<GeneratedTableSpec>

const timeseriesSeriesSchema = z.object({
  key: z.string(),
  label: z.string()
}) satisfies z.ZodType<GeneratedChartSeries>

const timeseriesViewSpecSchema = z.object({
  kind: z.literal('timeseries'),
  id: z.string(),
  title: z.string(),
  x: z.string(),
  series: z.array(timeseriesSeriesSchema).min(1).max(8),
  y_format: z.string().nullable().optional(),
  rows: z.array(z.record(z.string(), z.unknown()))
}) satisfies z.ZodType<GeneratedTimeseriesChartSpec>

/** Catches a spec whose columns/series reference a key no row actually
 * has (a model or server bug, not a shape violation Zod's structural check
 * alone would catch) - checked against the first row only, since every row
 * in a `ViewSpec` shares one column set. */
function checkKeysExistInRows(
  keys: string[],
  rows: Record<string, unknown>[],
  ctx: z.RefinementCtx
): void {
  const firstRow = rows[0]
  if (firstRow === undefined) return
  for (const key of keys) {
    if (!(key in firstRow)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `"${key}" is not a key of any row`,
        path: ['rows', 0, key]
      })
    }
  }
}

export const viewSpecSchema = z
  .discriminatedUnion('kind', [tableViewSpecSchema, timeseriesViewSpecSchema])
  .superRefine((spec, ctx) => {
    if (spec.kind === 'table') {
      checkKeysExistInRows(
        spec.columns.map((column) => column.key),
        spec.rows,
        ctx
      )
    } else {
      checkKeysExistInRows(
        [spec.x, ...spec.series.map((series) => series.key)],
        spec.rows,
        ctx
      )
    }
  })

export type TableViewSpec = z.infer<typeof tableViewSpecSchema>
export type TimeseriesViewSpec = z.infer<typeof timeseriesViewSpecSchema>
export type ViewSpec = z.infer<typeof viewSpecSchema>

export type ChatUIMessage = UIMessage<never, { view: ViewSpec }>
export type ChatUIMessagePart = UIMessagePart<{ view: ViewSpec }, never>
export type DataViewPart = Extract<ChatUIMessagePart, { type: 'data-view' }>

export function isDataViewPart(part: ChatUIMessagePart): part is DataViewPart {
  return part.type === 'data-view'
}

export interface ParsedViewSpec {
  success: true
  data: ViewSpec
}

export interface InvalidViewSpec {
  success: false
  error: string
}

/** Runtime validation for a `data-view` part's payload - the stream is
 * server-controlled today, but this is the seam that keeps a malformed or
 * future-shaped payload from crashing the chart/table renderer. */
export function parseViewSpec(data: unknown): ParsedViewSpec | InvalidViewSpec {
  const result = viewSpecSchema.safeParse(data)
  if (result.success) {
    return { success: true, data: result.data }
  }
  return { success: false, error: result.error.message }
}

/** One conversation, created by the app shell and held there, so it
 * survives the Ask panel closing, or moving between the docked column and
 * the full-screen sheet. */
export function createStockTickerChat(): Chat<ChatUIMessage> {
  return new Chat<ChatUIMessage>({ transport: chatTransport })
}

export function useStockTickerChat(chat: Chat<ChatUIMessage>) {
  return useChat<ChatUIMessage>({ chat })
}
