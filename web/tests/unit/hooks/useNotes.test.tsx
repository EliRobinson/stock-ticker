import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  QueryClient,
  QueryClientProvider,
  type InfiniteData
} from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import {
  createNoteId,
  notesKeys,
  removeNoteFromPages,
  upsertNoteInPages,
  useDeleteNote,
  usePutNote
} from '@/hooks/useNotes'
import type { Note, Paginated } from '@/lib/api'

function makeNote(overrides: Partial<Note> = {}): Note {
  return {
    id: 'note-1',
    cik: null,
    start_date: '2024-06-03',
    end_date: '2024-06-03',
    body: 'hello',
    created_at: '2024-06-03T00:00:00.000Z',
    updated_at: '2024-06-03T00:00:00.000Z',
    ...overrides
  }
}

function page(
  items: Note[],
  nextCursor: string | null = null
): Paginated<Note> {
  return { items, next_cursor: nextCursor }
}

describe('createNoteId', () => {
  it('generates a UUID', () => {
    expect(createNoteId()).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('generates a different id each call', () => {
    expect(createNoteId()).not.toBe(createNoteId())
  })
})

describe('upsertNoteInPages', () => {
  it('returns undefined data unchanged', () => {
    expect(upsertNoteInPages(undefined, makeNote())).toBeUndefined()
  })

  it('prepends a new note to the first page', () => {
    const data: InfiniteData<Paginated<Note>> = {
      pages: [page([makeNote({ id: 'existing' })])],
      pageParams: [undefined]
    }
    const result = upsertNoteInPages(data, makeNote({ id: 'new' }))
    expect(result?.pages[0]?.items.map((n) => n.id)).toEqual([
      'new',
      'existing'
    ])
  })

  it('replaces an existing note in place instead of duplicating it', () => {
    const data: InfiniteData<Paginated<Note>> = {
      pages: [page([makeNote({ id: 'note-1', body: 'old' })])],
      pageParams: [undefined]
    }
    const result = upsertNoteInPages(
      data,
      makeNote({ id: 'note-1', body: 'new' })
    )
    expect(result?.pages[0]?.items).toHaveLength(1)
    expect(result?.pages[0]?.items[0]?.body).toBe('new')
  })
})

describe('removeNoteFromPages', () => {
  it('returns undefined data unchanged', () => {
    expect(removeNoteFromPages(undefined, 'note-1')).toBeUndefined()
  })

  it('removes the matching note from every page', () => {
    const data: InfiniteData<Paginated<Note>> = {
      pages: [page([makeNote({ id: 'a' }), makeNote({ id: 'b' })])],
      pageParams: [undefined]
    }
    const result = removeNoteFromPages(data, 'a')
    expect(result?.pages[0]?.items.map((n) => n.id)).toEqual(['b'])
  })
})

describe('usePutNote / useDeleteNote', () => {
  let queryClient: QueryClient

  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
    })
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('optimistically writes the note before the PUT resolves, then settles on the server response', async () => {
    const params = { cik: '0000320193' }
    queryClient.setQueryData(notesKeys.list(params), {
      pages: [page([])],
      pageParams: [undefined]
    } satisfies InfiniteData<Paginated<Note>>)

    const serverNote = makeNote({ id: 'note-1', body: 'server body' })
    let resolveFetch: (value: Response) => void = () => {}
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveFetch = resolve
      })
    )

    const { result } = renderHook(() => usePutNote(), { wrapper })

    result.current.mutate({
      id: 'note-1',
      cik: '0000320193',
      start_date: '2024-06-03',
      body: 'optimistic body'
    })

    await waitFor(() => {
      const cached = queryClient.getQueryData<InfiniteData<Paginated<Note>>>(
        notesKeys.list(params)
      )
      expect(cached?.pages[0]?.items[0]?.body).toBe('optimistic body')
    })

    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    resolveFetch(
      new Response(JSON.stringify(serverNote), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    )

    // Settling invalidates notesKeys rather than writing the server
    // response into every cached page itself - the chart markers and any
    // mounted list share one cache and refetch it, so there is exactly one
    // place that reconciles with the server.
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(serverNote)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: notesKeys.all })
  })

  it('rolls back the optimistic write when the PUT fails', async () => {
    const params = { cik: '0000320193' }
    const original = page([makeNote({ id: 'note-1', body: 'original body' })])
    queryClient.setQueryData(notesKeys.list(params), {
      pages: [original],
      pageParams: [undefined]
    } satisfies InfiniteData<Paginated<Note>>)

    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          type: 'about:blank',
          title: 'Server error',
          status: 500
        }),
        {
          status: 500,
          headers: { 'Content-Type': 'application/json' }
        }
      )
    )

    const { result } = renderHook(() => usePutNote(), { wrapper })

    result.current.mutate({
      id: 'note-1',
      cik: '0000320193',
      start_date: '2024-06-03',
      body: 'will fail'
    })

    await waitFor(() => expect(result.current.isError).toBe(true))

    const cached = queryClient.getQueryData<InfiniteData<Paginated<Note>>>(
      notesKeys.list(params)
    )
    expect(cached?.pages[0]?.items[0]?.body).toBe('original body')
  })

  it('optimistically removes a note on delete and rolls back on error', async () => {
    const params = { cik: '0000320193' }
    queryClient.setQueryData(notesKeys.list(params), {
      pages: [page([makeNote({ id: 'note-1' })])],
      pageParams: [undefined]
    } satisfies InfiniteData<Paginated<Note>>)

    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          type: 'about:blank',
          title: 'Server error',
          status: 500
        }),
        {
          status: 500,
          headers: { 'Content-Type': 'application/json' }
        }
      )
    )

    const { result } = renderHook(() => useDeleteNote(), { wrapper })

    result.current.mutate('note-1')

    // The 500 response resolves on a microtask, so onMutate's removal and
    // onError's rollback can both land before the next `waitFor` poll -
    // only the settled, rolled-back state is guaranteed to be observable.
    await waitFor(() => expect(result.current.isError).toBe(true))

    const cached = queryClient.getQueryData<InfiniteData<Paginated<Note>>>(
      notesKeys.list(params)
    )
    expect(cached?.pages[0]?.items.map((n) => n.id)).toEqual(['note-1'])
  })
})
