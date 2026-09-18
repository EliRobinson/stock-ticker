import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { UIMessage, UIMessagePart } from 'ai'
import { z } from 'zod'
import { env } from '@/env'

/** Created once, not per render/per hook call - a fresh transport instance
 * on every render is wasted work and has no reason to differ between
 * callers, since every chat surface hits the same endpoint. */
const chatTransport = new DefaultChatTransport({
  api: `${env.NEXT_PUBLIC_API_URL}/api/v1/chat`
})

/**
 * The stub `/api/v1/chat` route in web/openapi/openapi.json documents no
 * response body yet, so `ViewSpec` isn't in the generated api-types.ts. This
 * schema was confirmed directly with the #7 (ai-chat) agent, which validates
 * its golden streams against the same shape with ai@7.0.106's
 * uiMessageChunkSchema - swap this for its generated DataViewPart/
 * TableSpec/TimeseriesChartSpec once feat/ai-chat pushes the OpenAPI
 * components.
 */
const viewValueFormatSchema = z
  .enum([
    'text',
    'integer',
    'number',
    'currency',
    'compact_currency',
    'percent',
    'fraction_as_percent',
    'date',
    'datetime'
  ])
  .nullable()

const viewColumnSchema = z.object({
  key: z.string(),
  label: z.string(),
  format: viewValueFormatSchema
})

const tableViewSpecSchema = z.object({
  kind: z.literal('table'),
  id: z.string(),
  title: z.string(),
  columns: z.array(viewColumnSchema),
  rows: z.array(z.record(z.string(), z.unknown()))
})

const timeseriesSeriesSchema = z.object({
  key: z.string(),
  label: z.string()
})

const timeseriesViewSpecSchema = z.object({
  kind: z.literal('timeseries'),
  id: z.string(),
  title: z.string(),
  x: z.string(),
  series: z.array(timeseriesSeriesSchema).min(1).max(8),
  y_format: viewValueFormatSchema,
  rows: z.array(z.record(z.string(), z.unknown()))
})

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

export function useStockTickerChat() {
  return useChat<ChatUIMessage>({ transport: chatTransport })
}
