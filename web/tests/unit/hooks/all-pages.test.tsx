import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useEvents } from '@/hooks/useEvents'
import { useNotes, useSaveNote } from '@/hooks/useNotes'

import {
  AAPL_CIK,
  jsonResponse,
  makeEvent,
  makeNote,
  problemResponse
} from '../fixtures'

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('list hooks fetch every page', () => {
  it('useNotes follows next_cursor to the end and flattens', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : String(input))
      const cursor = url.searchParams.get('cursor')
      expect(url.searchParams.get('limit')).toBe('1000')
      return jsonResponse(
        cursor
          ? { items: [makeNote({ id: 'b' })], next_cursor: null }
          : { items: [makeNote({ id: 'a' })], next_cursor: 'page-2' }
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useNotes({ cik: AAPL_CIK }), {
      wrapper: wrapper()
    })
    await waitFor(() =>
      expect(result.current.data?.map((n) => n.id)).toEqual(['a', 'b'])
    )
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('useEvents does the same', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(
          input instanceof Request ? input.url : String(input)
        )
        return jsonResponse(
          url.searchParams.get('cursor')
            ? { items: [makeEvent({ id: 2 })], next_cursor: null }
            : { items: [makeEvent({ id: 1 })], next_cursor: 'c2' }
        )
      })
    )
    const { result } = renderHook(() => useEvents({ cik: AAPL_CIK }), {
      wrapper: wrapper()
    })
    await waitFor(() =>
      expect(result.current.data?.map((e) => e.id)).toEqual([1, 2])
    )
  })
})

describe('useSaveNote', () => {
  it('mints an id for a new Note and resolves with the saved Note', async () => {
    const saved = makeNote({ id: 'server' })
    const fetchMock = vi.fn(async () => jsonResponse(saved))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useSaveNote(), { wrapper: wrapper() })
    await expect(
      result.current.save({
        cik: AAPL_CIK,
        start_date: '2024-06-03',
        body: 'x'
      })
    ).resolves.toEqual(saved)
    const request = fetchMock.mock.calls[0]![0] as unknown as Request | string
    const url = request instanceof Request ? request.url : String(request)
    expect(url).toMatch(/\/api\/v1\/notes\/[0-9a-f-]{36}$/)
  })

  it('rejects when the save fails, so the caller can keep the form open', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => problemResponse(503))
    )
    const { result } = renderHook(() => useSaveNote(), { wrapper: wrapper() })
    await expect(
      result.current.save({
        id: 'n1',
        cik: null,
        start_date: '2024-06-03',
        body: 'x'
      })
    ).rejects.toThrow()
  })
})
