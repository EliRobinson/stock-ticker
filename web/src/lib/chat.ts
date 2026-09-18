import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import type { UIMessage, UIMessagePart } from 'ai'
import { z } from 'zod'
import { env } from '@/env'

/**
 * The stub `/api/v1/chat` route in web/openapi/openapi.json documents no
 * response body yet, so `ViewSpec` isn't in the generated api-types.ts. This
 * schema follows the target contract from docs/design/system-design.md §6
 * ("ViewSpec is a Pydantic discriminated union on kind") - swap this for a
 * generated type the day the chat route ships its OpenAPI response model.
 */
const viewColumnSchema = z.object({
  key: z.string(),
  label: z.string(),
  format: z.string().optional()
})

const tableViewSpecSchema = z.object({
  kind: z.literal('table'),
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
  title: z.string(),
  x: z.string(),
  series: z.array(timeseriesSeriesSchema),
  y_format: z.string().optional(),
  rows: z.array(z.record(z.string(), z.unknown()))
})

export const viewSpecSchema = z.discriminatedUnion('kind', [
  tableViewSpecSchema,
  timeseriesViewSpecSchema
])

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
  return useChat<ChatUIMessage>({
    transport: new DefaultChatTransport({
      api: `${env.NEXT_PUBLIC_API_URL}/api/v1/chat`
    })
  })
}
