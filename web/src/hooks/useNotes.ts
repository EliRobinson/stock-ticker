import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
  type QueryKey
} from '@tanstack/react-query'
import {
  deleteNote,
  getNotes,
  putNote,
  type GetNotesParams,
  type Note,
  type NotesResponse,
  type NoteUpsert
} from '@/lib/api'

export const notesKeys = {
  all: ['notes'] as const,
  list: (params: Omit<GetNotesParams, 'cursor'>) =>
    [...notesKeys.all, params] as const
}

const STALE_TIME_MS = 60 * 1000

export function useNotes(params: Omit<GetNotesParams, 'cursor'> = {}) {
  return useInfiniteQuery({
    queryKey: notesKeys.list(params),
    queryFn: ({ pageParam }) => getNotes({ ...params, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    staleTime: STALE_TIME_MS
  })
}

/** The client, not the server, owns note identity - a PUT with a fresh id
 * creates, and Undo re-PUTs the same id instead of minting a new one. */
export function createNoteId(): string {
  return crypto.randomUUID()
}

type NotesInfiniteData = InfiniteData<NotesResponse>
type NotesCacheEntry = [QueryKey, NotesInfiniteData | undefined]
type NotesListParams = Omit<GetNotesParams, 'cursor'>

/**
 * The same predicate the API applies (system-design.md §5): with
 * `market_only`, cik is ignored and only cik === null matches; otherwise a
 * `cik` filter requires an exact match; `from`/`to` is a range overlap
 * against the Note's own [start_date, end_date]. `include_market` (a
 * combined "this Company's notes plus market-wide notes" view) is not a
 * query param GET /notes accepts today - confirmed against feat/api-read's
 * committed api/openapi.json - so it isn't modeled here; add it once the
 * API actually supports it instead of guessing the semantics.
 */
export function noteMatchesList(params: NotesListParams, note: Note): boolean {
  if (params.market_only) {
    return note.cik === null
  }
  if (params.cik !== undefined && note.cik !== params.cik) {
    return false
  }
  if (params.from !== undefined && note.end_date < params.from) {
    return false
  }
  if (params.to !== undefined && note.start_date > params.to) {
    return false
  }
  return true
}

export function upsertNoteInPages(
  data: NotesInfiniteData | undefined,
  note: Note
): NotesInfiniteData | undefined {
  if (!data) return data

  let replaced = false
  const pages = data.pages.map((page) => ({
    ...page,
    items: page.items.map((existing) => {
      if (existing.id !== note.id) return existing
      replaced = true
      return note
    })
  }))

  if (replaced) return { ...data, pages }

  const [first, ...rest] = pages
  const firstPage = first ?? { items: [], next_cursor: null }
  return {
    ...data,
    pages: [{ ...firstPage, items: [note, ...firstPage.items] }, ...rest]
  }
}

export function removeNoteFromPages(
  data: NotesInfiniteData | undefined,
  id: string
): NotesInfiniteData | undefined {
  if (!data) return data
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.filter((note) => note.id !== id)
    }))
  }
}

function findNotesQueries(queryClient: QueryClient) {
  return queryClient.getQueryCache().findAll({ queryKey: notesKeys.all })
}

function paramsOf(queryKey: QueryKey): NotesListParams | undefined {
  const params = queryKey[1]
  return typeof params === 'object' && params !== null
    ? (params as NotesListParams)
    : undefined
}

export interface PutNoteVariables extends NoteUpsert {
  id: string
}

const NOTES_MUTATION_KEY = ['notes']

export function usePutNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationKey: NOTES_MUTATION_KEY,
    // Serializes concurrent Note edits against each other (and against
    // useDeleteNote) instead of letting two in-flight mutations race their
    // optimistic writes and rollbacks against the same cache entries.
    scope: { id: 'notes' },
    mutationFn: (vars: PutNoteVariables) =>
      putNote(vars.id, {
        cik: vars.cik ?? null,
        start_date: vars.start_date,
        end_date: vars.end_date,
        body: vars.body
      }),
    onMutate: async (vars) => {
      await queryClient.cancelQueries({ queryKey: notesKeys.all })

      const now = new Date().toISOString()
      const optimisticNote: Note = {
        id: vars.id,
        cik: vars.cik ?? null,
        start_date: vars.start_date,
        end_date: vars.end_date ?? vars.start_date,
        body: vars.body,
        created_at: now,
        updated_at: now
      }

      const queries = findNotesQueries(queryClient)
      const previous: NotesCacheEntry[] = queries.map((query) => [
        query.queryKey,
        query.state.data as NotesInfiniteData | undefined
      ])

      // Only a list whose own filter (cik/market_only/range) actually
      // matches this Note gets the optimistic write - a Note for AAPL must
      // not appear in a cached list scoped to MSFT. A list the Note no
      // longer matches (its cik changed in this edit) gets it removed, so
      // an edit optimistically moves the Note between lists instead of
      // leaving a stale copy behind.
      for (const query of queries) {
        const params = paramsOf(query.queryKey)
        if (params === undefined) continue
        const matches = noteMatchesList(params, optimisticNote)
        queryClient.setQueryData<NotesInfiniteData>(query.queryKey, (old) =>
          matches
            ? upsertNoteInPages(old, optimisticNote)
            : removeNoteFromPages(old, optimisticNote.id)
        )
      }

      return { previous }
    },
    onError: (_error, _vars, context) => {
      context?.previous.forEach(([queryKey, data]) => {
        queryClient.setQueryData(queryKey, data)
      })
    },
    onSettled: () => {
      // Two edits in flight both settle, but only the last one should
      // trigger a refetch - invalidating after the first would refetch
      // stale (pre-second-edit) server state into the cache.
      if (queryClient.isMutating({ mutationKey: NOTES_MUTATION_KEY }) === 1) {
        queryClient.invalidateQueries({ queryKey: notesKeys.all })
      }
    }
  })
}

export function useDeleteNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationKey: NOTES_MUTATION_KEY,
    scope: { id: 'notes' },
    mutationFn: (id: string) => deleteNote(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: notesKeys.all })
      const queries = findNotesQueries(queryClient)
      const previous: NotesCacheEntry[] = queries.map((query) => [
        query.queryKey,
        query.state.data as NotesInfiniteData | undefined
      ])

      // Removing an absent id from a page is a no-op filter, so every
      // cached list can be touched safely - there's no "wrong list" case
      // for a delete the way there is for an optimistic add/edit.
      queryClient.setQueriesData<NotesInfiniteData>(
        { queryKey: notesKeys.all },
        (old) => removeNoteFromPages(old, id)
      )

      return { previous }
    },
    onError: (_error, _id, context) => {
      context?.previous.forEach(([queryKey, data]) => {
        queryClient.setQueryData(queryKey, data)
      })
    },
    onSettled: () => {
      if (queryClient.isMutating({ mutationKey: NOTES_MUTATION_KEY }) === 1) {
        queryClient.invalidateQueries({ queryKey: notesKeys.all })
      }
    }
  })
}
