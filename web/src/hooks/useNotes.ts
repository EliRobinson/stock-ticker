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
  toNotePut,
  type Note,
  type NotesListParams,
  type NotesResponse,
  type PutNoteBody
} from '@/lib/api'
import {
  LIST_PAGE_LIMIT,
  NOTES_STALE_TIME_MS,
  cursorPaging
} from '@/lib/query-config'

import { flattenPages, useAllPages } from './useAllPages'

export const notesKeys = {
  all: ['notes'] as const,
  list: (params: NotesListParams) => [...notesKeys.all, params] as const
}

/** Every Note matching `params`, all pages, flattened. */
export function useNotes(params: NotesListParams = {}) {
  const query = useInfiniteQuery({
    queryKey: notesKeys.list(params),
    queryFn: ({ pageParam }) =>
      getNotes({ limit: LIST_PAGE_LIMIT, ...params, cursor: pageParam }),
    ...cursorPaging,
    staleTime: NOTES_STALE_TIME_MS,
    select: flattenPages
  })
  useAllPages(query)
  return query
}

/** The client, not the server, owns note identity - a PUT with a fresh id
 * creates, and Undo re-PUTs the same id instead of minting a new one. */
export function createNoteId(): string {
  return crypto.randomUUID()
}

type NotesInfiniteData = InfiniteData<NotesResponse>
type NotesCacheEntry = [QueryKey, NotesInfiniteData | undefined]

/**
 * The same predicate the API applies (system-design.md §5, amended by the
 * #8 review): with `market_only`, cik is ignored and only cik === null
 * matches. A `cik` filter requires an exact match, unless `include_market`
 * is also set - the route's own rule (api-read, confirmed against its
 * committed api/openapi.json) - in which case a whole-market Note
 * (cik === null) matches too, alongside that cik's own Notes. `cik` and
 * `market_only` together is a route-level 422 (conflicting filters); this
 * assumes the params it's given are valid, same as the route does.
 * `from`/`to` is a range overlap against the Note's own
 * [start_date, end_date].
 */
export function noteMatchesList(params: NotesListParams, note: Note): boolean {
  if (params.market_only) {
    return note.cik === null
  }
  if (params.cik !== undefined) {
    const matchesCik = note.cik === params.cik
    const matchesMarket = params.include_market && note.cik === null
    if (!matchesCik && !matchesMarket) return false
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

/** Captures every currently-cached notes query's data, for onError to
 * restore. Shared by usePutNote and useDeleteNote's onMutate. */
function snapshotNotes(queryClient: QueryClient): NotesCacheEntry[] {
  return findNotesQueries(queryClient).map((query) => [
    query.queryKey,
    query.state.data as NotesInfiniteData | undefined
  ])
}

/** The onError half of snapshotNotes - writes each captured entry back
 * exactly as it was before the optimistic write. */
function restoreNotes(
  queryClient: QueryClient,
  previous: NotesCacheEntry[] | undefined
): void {
  previous?.forEach(([queryKey, data]) => {
    queryClient.setQueryData(queryKey, data)
  })
}

/** Two edits in flight both settle, but only the last one should trigger
 * a refetch - invalidating after the first would refetch stale
 * (pre-second-edit) server state into the cache. */
function invalidateNotesWhenIdle(queryClient: QueryClient): void {
  if (queryClient.isMutating({ mutationKey: NOTES_MUTATION_KEY }) === 1) {
    queryClient.invalidateQueries({ queryKey: notesKeys.all })
  }
}

export interface PutNoteVariables extends PutNoteBody {
  id: string
}

const NOTES_MUTATION_KEY = notesKeys.all
// Serializes concurrent Note edits/deletes against each other instead of
// letting two in-flight mutations race their optimistic writes and
// rollbacks against the same cache entries.
const NOTES_SCOPE = { id: 'notes' }

export function usePutNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationKey: NOTES_MUTATION_KEY,
    scope: NOTES_SCOPE,
    mutationFn: (vars: PutNoteVariables) => putNote(vars.id, vars),
    onMutate: async (vars) => {
      await queryClient.cancelQueries({ queryKey: notesKeys.all })

      const now = new Date().toISOString()
      const optimisticNote: Note = {
        id: vars.id,
        ...toNotePut(vars),
        created_at: now,
        updated_at: now
      }

      const queries = findNotesQueries(queryClient)
      const previous = snapshotNotes(queryClient)

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
    onError: (_error, _vars, context) =>
      restoreNotes(queryClient, context?.previous),
    onSettled: () => invalidateNotesWhenIdle(queryClient)
  })
}

export function useDeleteNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationKey: NOTES_MUTATION_KEY,
    scope: NOTES_SCOPE,
    mutationFn: (id: string) => deleteNote(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: notesKeys.all })
      const previous = snapshotNotes(queryClient)

      // Removing an absent id from a page is a no-op filter, so every
      // cached list can be touched safely - there's no "wrong list" case
      // for a delete the way there is for an optimistic add/edit.
      queryClient.setQueriesData<NotesInfiniteData>(
        { queryKey: notesKeys.all },
        (old) => removeNoteFromPages(old, id)
      )

      return { previous }
    },
    onError: (_error, _id, context) =>
      restoreNotes(queryClient, context?.previous),
    onSettled: () => invalidateNotesWhenIdle(queryClient)
  })
}

export interface NoteDraft extends PutNoteBody {
  id?: string
}

/** Saves a new or edited Note and resolves with the stored Note, so a form
 * can stay open (with its text) until the save succeeds. */
export function useSaveNote() {
  const putNote = usePutNote()
  return {
    ...putNote,
    save: (draft: NoteDraft) =>
      putNote.mutateAsync({ ...draft, id: draft.id ?? createNoteId() })
  }
}
