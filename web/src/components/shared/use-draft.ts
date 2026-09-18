'use client'

import { useState } from 'react'

// A text input backed by a slow store (the URL, written after a debounce).
// The input owns what's typed and updates at once. The stored value only
// overwrites it when it changes from outside (back button, a link, Clear
// filters elsewhere), never when it echoes a value this input already sent,
// even an older one that lands after more typing.
export function useDraft(value: string, onChange: (value: string) => void) {
  const [draft, setDraft] = useState(value)
  const [seen, setSeen] = useState(value)
  const [sent, setSent] = useState<ReadonlySet<string>>(() => new Set([value]))
  if (value !== seen) {
    setSeen(value)
    if (!sent.has(value)) {
      setSent(new Set([value]))
      setDraft(value)
    }
  }
  const change = (next: string) => {
    setDraft(next)
    setSent((prev) => new Set(prev).add(next))
    onChange(next)
  }
  return [draft, change] as const
}
