'use client'

import { useStatus } from '@/hooks/useStatus'
import type { StatusResponse } from '@/lib/api'
import { useStockTickerChat } from '@/lib/chat'

import { AskPanel } from '../ask/ask-panel'
import { askCopy } from '../ask/copy'
import type { AskUnavailable } from '../ask/types'
import { formatUsd } from '../shared/format'
import type { AiStatus } from '../shell/status-strip'

export function readAiStatus(
  status: StatusResponse | undefined
): AiStatus | null {
  return status?.ai ?? null
}

export function AskContainer({ onClose }: { onClose: () => void }) {
  const chat = useStockTickerChat()
  const { data: status } = useStatus()
  const ai = readAiStatus(status)

  const unavailable: AskUnavailable = status?.missing_keys.includes(
    'ANTHROPIC_API_KEY'
  )
    ? 'missing-key'
    : ai && !ai.enabled && ai.spend_usd >= ai.limit_usd
      ? 'spend-limit'
      : null

  // The stream's own errorText is shown as sent (#7). A failed fetch never
  // reaches the stream, so it gets the brief's "backend down" copy instead.
  const message = chat.error?.message
  const error = chat.error
    ? !message || /fetch|network|load failed/i.test(message)
      ? askCopy.errors['backend-down']
      : message
    : null

  return (
    <AskPanel
      messages={chat.messages}
      status={chat.status}
      error={error}
      unavailable={unavailable}
      spendLimit={ai ? formatUsd(ai.limit_usd) : undefined}
      onSend={(text) => {
        chat.sendMessage({ text }).catch(() => {})
      }}
      onRetry={() => {
        chat.regenerate().catch(() => {})
      }}
      onStop={() => {
        chat.stop().catch(() => {})
      }}
      onClose={onClose}
    />
  )
}
