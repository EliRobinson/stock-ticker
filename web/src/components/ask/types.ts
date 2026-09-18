import type { ChatUIMessage } from '@/lib/chat'

export type AskMessage = ChatUIMessage

// `tool-run_sql` part payloads, as confirmed with #7 (feat/ai-chat).
export interface RunSqlInput {
  sql: string
  purpose: string
}

export interface RunSqlOutput {
  result_id: string
  row_count: number
  row_count_is_capped: boolean
  truncated: boolean
}

export type AskStatus = 'ready' | 'submitted' | 'streaming' | 'error'

export type AskUnavailable = 'missing-key' | 'spend-limit' | null
