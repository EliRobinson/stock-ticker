import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
  type InfiniteData,
  type QueryKey
} from '@tanstack/react-query'
import {
  deleteNote,
  getNotes,
  putNote,
  type GetNotesParams,
  type Note,
  type Paginated,
  type PutNoteBody
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

type NotesInfiniteData = InfiniteData<Paginated<Note>>
type NotesCacheEntry = [QueryKey, NotesInfiniteData | undefined]

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

export interface PutNoteVariables extends PutNoteBody {
  id: string
}

export function usePutNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (vars: PutNoteVariables) =>
      putNote(vars.id, {
        cik: vars.cik ?? null,
        start_date: vars.start_date,
        end_date: vars.end_date,
        body: vars.body
      }),
    onMutate: async (vars) => {
      await queryClient.cancelQueries({ queryKey: notesKeys.all })
      const previous = queryClient.getQueriesData<NotesInfiniteData>({
        queryKey: notesKeys.all
      }) as NotesCacheEntry[]

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

      queryClient.setQueriesData<NotesInfiniteData>(
        { queryKey: notesKeys.all },
        (old) => upsertNoteInPages(old, optimisticNote)
      )

      return { previous }
    },
    onError: (_error, _vars, context) => {
      context?.previous.forEach(([queryKey, data]) => {
        queryClient.setQueryData(queryKey, data)
      })
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notesKeys.all })
    }
  })
}

export function useDeleteNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => deleteNote(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: notesKeys.all })
      const previous = queryClient.getQueriesData<NotesInfiniteData>({
        queryKey: notesKeys.all
      }) as NotesCacheEntry[]

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
      queryClient.invalidateQueries({ queryKey: notesKeys.all })
    }
  })
}
