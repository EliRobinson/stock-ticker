'use client'

import type { Chat } from '@ai-sdk/react'
import { useMemo } from 'react'

import { useStatus } from '@/hooks/useStatus'
import type { StatusResponse } from '@/lib/api'
import { useStockTickerChat } from '@/lib/chat'
import type { ChatUIMessage } from '@/lib/chat'
import { formatUsd } from '@/lib/format'

import { AskPanel } from '../ask/ask-panel'
import { askCopy } from '../ask/copy'
import { prepareTurns } from '../ask/prepare'
import type { AskUnavailable } from '../ask/types'

export function askUnavailable(
  status: StatusResponse | undefined
): AskUnavailable {
  if (!status) return null
  if (status.missing_keys.includes('ANTHROPIC_API_KEY')) return 'missing-key'
  const ai = status.ai
  if (ai && !ai.enabled && ai.spend_usd >= ai.limit_usd) return 'spend-limit'
  return null
}

// The stream's own errorText is shown as sent (#7). A request that never
// reached the stream (the API is down) gets the brief's "unreachable" copy.
export function askErrorText(error: Error | undefined): string | null {
  if (!error) return null
  const message = error.message
  if (!message || /fetch|network|load failed/i.test(message)) {
    return askCopy.errors['backend-down']
  }
  return message
}

export function AskContainer({
  chat,
  onClose
}: {
  chat: Chat<ChatUIMessage>
  onClose: () => void
}) {
  const { messages, status, error, sendMessage, regenerate, stop } =
    useStockTickerChat(chat)
  const { data: statusData } = useStatus()
  const turns = useMemo(
    () => prepareTurns(messages, status),
    [messages, status]
  )
  const ai = statusData?.ai

  return (
    <AskPanel
      turns={turns}
      status={status}
      error={askErrorText(error)}
      unavailable={askUnavailable(statusData)}
      spendLimit={ai ? formatUsd(ai.limit_usd) : undefined}
      onSend={(text) => {
        sendMessage({ text }).catch(() => {})
      }}
      onRetry={() => {
        regenerate().catch(() => {})
      }}
      onStop={() => {
        stop().catch(() => {})
      }}
      onClose={onClose}
    />
  )
}
