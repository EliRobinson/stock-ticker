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
  noteMatchesList,
  notesKeys,
  removeNoteFromPages,
  upsertNoteInPages,
  useDeleteNote,
  usePutNote
} from '@/hooks/useNotes'
import type { NotesResponse } from '@/lib/api'
import { AAPL_CIK, infinitePages, makeNote, problemResponse } from '../fixtures'

/** A second Company's cik, only used to prove a Note stays out of a list
 * scoped to a different Company - not a shared fixture, since nothing
 * else in this file cares which company it is. */
const MSFT_CIK = '0000789019'

describe('createNoteId', () => {
  it('generates a UUID', () => {
    expect(createNoteId()).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('generates a different id each call', () => {
    expect(createNoteId()).not.toBe(createNoteId())
  })
})

describe('noteMatchesList', () => {
  it('matches a note with no filter params at all', () => {
    expect(noteMatchesList({}, makeNote({ cik: AAPL_CIK }))).toBe(true)
    expect(noteMatchesList({}, makeNote({ cik: null }))).toBe(true)
  })

  it('requires an exact cik match when cik is filtered', () => {
    const note = makeNote({ cik: AAPL_CIK })
    expect(noteMatchesList({ cik: AAPL_CIK }, note)).toBe(true)
    expect(noteMatchesList({ cik: MSFT_CIK }, note)).toBe(false)
  })

  it('a cik filter excludes a market-wide note', () => {
    expect(noteMatchesList({ cik: AAPL_CIK }, makeNote({ cik: null }))).toBe(
      false
    )
  })

  it('market_only matches only market-wide notes, ignoring any cik filter', () => {
    expect(
      noteMatchesList(
        { cik: AAPL_CIK, market_only: true },
        makeNote({ cik: null })
      )
    ).toBe(true)
    expect(
      noteMatchesList({ market_only: true }, makeNote({ cik: AAPL_CIK }))
    ).toBe(false)
  })

  it('include_market matches a market-wide note alongside a cik filter', () => {
    expect(
      noteMatchesList(
        { cik: AAPL_CIK, include_market: true },
        makeNote({ cik: null })
      )
    ).toBe(true)
    expect(
      noteMatchesList(
        { cik: AAPL_CIK, include_market: true },
        makeNote({ cik: AAPL_CIK })
      )
    ).toBe(true)
    expect(
      noteMatchesList(
        { cik: AAPL_CIK, include_market: true },
        makeNote({ cik: MSFT_CIK })
      )
    ).toBe(false)
  })

  it('without include_market, a cik filter still excludes market-wide notes', () => {
    expect(noteMatchesList({ cik: AAPL_CIK }, makeNote({ cik: null }))).toBe(
      false
    )
  })

  it('matches a note whose range overlaps the from/to window', () => {
    const note = makeNote({ start_date: '2024-06-01', end_date: '2024-06-10' })
    expect(
      noteMatchesList({ from: '2024-06-05', to: '2024-06-06' }, note)
    ).toBe(true)
    expect(
      noteMatchesList({ from: '2024-05-01', to: '2024-06-02' }, note)
    ).toBe(true)
    expect(
      noteMatchesList({ from: '2024-06-09', to: '2024-07-01' }, note)
    ).toBe(true)
  })

  it('rejects a note entirely outside the from/to window', () => {
    const note = makeNote({ start_date: '2024-01-01', end_date: '2024-01-02' })
    expect(noteMatchesList({ from: '2024-06-01' }, note)).toBe(false)
    expect(noteMatchesList({ to: '2023-12-31' }, note)).toBe(false)
  })
})

describe('upsertNoteInPages', () => {
  it('returns undefined data unchanged', () => {
    expect(upsertNoteInPages(undefined, makeNote())).toBeUndefined()
  })

  it('prepends a new note to the first page', () => {
    const data = infinitePages([makeNote({ id: 'existing' })])
    const result = upsertNoteInPages(data, makeNote({ id: 'new' }))
    expect(result?.pages[0]?.items.map((n) => n.id)).toEqual([
      'new',
      'existing'
    ])
  })

  it('replaces an existing note in place instead of duplicating it', () => {
    const data = infinitePages([makeNote({ id: 'note-1', body: 'old' })])
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
    const data = infinitePages([makeNote({ id: 'a' }), makeNote({ id: 'b' })])
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
    const params = { cik: AAPL_CIK }
    queryClient.setQueryData(notesKeys.list(params), infinitePages([]))

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
      cik: AAPL_CIK,
      start_date: '2024-06-03',
      body: 'optimistic body'
    })

    await waitFor(() => {
      const cached = queryClient.getQueryData<InfiniteData<NotesResponse>>(
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

  it('does not add the note to a cached list its params do not match', async () => {
    const aaplParams = { cik: AAPL_CIK }
    const msftParams = { cik: MSFT_CIK }
    queryClient.setQueryData(notesKeys.list(aaplParams), infinitePages([]))
    queryClient.setQueryData(notesKeys.list(msftParams), infinitePages([]))

    const fetchMock = vi.mocked(fetch)
    fetchMock.mockReturnValueOnce(new Promise(() => {})) // never resolves in this test

    const { result } = renderHook(() => usePutNote(), { wrapper })
    result.current.mutate({
      id: 'note-1',
      cik: AAPL_CIK,
      start_date: '2024-06-03',
      body: 'AAPL note'
    })

    await waitFor(() => {
      const aapl = queryClient.getQueryData<InfiniteData<NotesResponse>>(
        notesKeys.list(aaplParams)
      )
      expect(aapl?.pages[0]?.items).toHaveLength(1)
    })

    const msft = queryClient.getQueryData<InfiniteData<NotesResponse>>(
      notesKeys.list(msftParams)
    )
    expect(msft?.pages[0]?.items).toHaveLength(0)
  })

  it('rolls back the optimistic write when the PUT fails', async () => {
    const params = { cik: AAPL_CIK }
    queryClient.setQueryData(
      notesKeys.list(params),
      infinitePages([makeNote({ id: 'note-1', body: 'original body' })])
    )

    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      problemResponse(500, { title: 'Server error' })
    )

    const { result } = renderHook(() => usePutNote(), { wrapper })

    result.current.mutate({
      id: 'note-1',
      cik: AAPL_CIK,
      start_date: '2024-06-03',
      body: 'will fail'
    })

    await waitFor(() => expect(result.current.isError).toBe(true))

    const cached = queryClient.getQueryData<InfiniteData<NotesResponse>>(
      notesKeys.list(params)
    )
    expect(cached?.pages[0]?.items[0]?.body).toBe('original body')
  })

  it('optimistically removes a note on delete and rolls back on error', async () => {
    const params = { cik: AAPL_CIK }
    queryClient.setQueryData(
      notesKeys.list(params),
      infinitePages([makeNote({ id: 'note-1' })])
    )

    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      problemResponse(500, { title: 'Server error' })
    )

    const { result } = renderHook(() => useDeleteNote(), { wrapper })

    result.current.mutate('note-1')

    // The 500 response resolves on a microtask, so onMutate's removal and
    // onError's rollback can both land before the next `waitFor` poll -
    // only the settled, rolled-back state is guaranteed to be observable.
    await waitFor(() => expect(result.current.isError).toBe(true))

    const cached = queryClient.getQueryData<InfiniteData<NotesResponse>>(
      notesKeys.list(params)
    )
    expect(cached?.pages[0]?.items.map((n) => n.id)).toEqual(['note-1'])
  })

  it('invalidates once, not once per mutation, when two edits settle close together', async () => {
    const params = { cik: AAPL_CIK }
    queryClient.setQueryData(
      notesKeys.list(params),
      infinitePages([makeNote({ id: 'note-1', body: 'original' })])
    )

    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(makeNote({ id: 'note-1', body: 'edit 2' })), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    )

    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const { result } = renderHook(() => usePutNote(), { wrapper })

    result.current.mutate({
      id: 'note-1',
      cik: AAPL_CIK,
      start_date: '2024-06-03',
      body: 'edit 1'
    })
    result.current.mutate({
      id: 'note-1',
      cik: AAPL_CIK,
      start_date: '2024-06-03',
      body: 'edit 2'
    })

    await waitFor(() => expect(invalidateSpy).toHaveBeenCalled())
    // Give any extra (incorrect) invalidate call from the first mutation's
    // settle a chance to also land before asserting there was only one.
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(invalidateSpy).toHaveBeenCalledTimes(1)
  })
})
