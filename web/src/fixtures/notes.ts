import type { Note, NotesResponse } from '@/lib/api'

const AAPL = '0000320193'
const TSM = '0001046179'

const note = (
  id: string,
  cik: string | null,
  start: string,
  end: string,
  body: string
): Note => ({
  id,
  cik,
  start_date: start,
  end_date: end,
  body,
  created_at: `${start}T20:00:00Z`,
  updated_at: `${start}T20:00:00Z`
})

export const notes: Note[] = [
  note(
    '6f1c2a4e-0001-4c55-9d0e-000000000001',
    AAPL,
    '2024-09-17',
    '2024-09-17',
    'Buyback pace slowed two quarters running. Not a thesis change, but the per-share math I was leaning on gets weaker from here.'
  ),
  note(
    '6f1c2a4e-0002-4c55-9d0e-000000000002',
    AAPL,
    '2024-08-05',
    '2024-09-12',
    'Drawdown looks like positioning, not demand. Backlog commentary in the 10-Q unchanged, capex guidance held.'
  ),
  note(
    '6f1c2a4e-0003-4c55-9d0e-000000000003',
    AAPL,
    '2023-06-12',
    '2023-06-12',
    'Services margin story finally showing in the multiple — reread the 10-Q segment table before adding.'
  ),
  note(
    '6f1c2a4e-0004-4c55-9d0e-000000000004',
    AAPL,
    '2022-01-03',
    '2022-01-03',
    'Three-trillion print. Recording it because round numbers move my behaviour and I want the receipt.'
  ),
  note(
    '6f1c2a4e-0005-4c55-9d0e-000000000005',
    AAPL,
    '2020-03-20',
    '2020-03-20',
    'Bought here. Reason at the time: cash pile, not the products.'
  ),
  note(
    '6f1c2a4e-0006-4c55-9d0e-000000000006',
    null,
    '2020-02-19',
    '2020-03-23',
    'The drawdown window I keep coming back to. What I want from it is not the depth — everything fell — but the **dispersion**: which balance sheets got repriced and which got re-rated, and how long the gap persisted after the index recovered. Energy and travel are the obvious tail; the interesting part is the second quartile, where a handful of industrials fell as hard as airlines and recovered in a third of the time.'
  ),
  note(
    '6f1c2a4e-0007-4c55-9d0e-000000000007',
    TSM,
    '2024-08-05',
    '2024-09-12',
    'The August drawdown looks like a positioning unwind, not a demand signal: order backlog commentary in the 10-Q is unchanged, capex guidance held, and the move retraced most of the way inside six sessions. What would change my mind is two consecutive months of declining monthly revenue against a flat exchange rate.'
  )
]

export const notesResponse: NotesResponse = {
  items: notes,
  next_cursor: null
}
export const notesEmpty: NotesResponse = { items: [], next_cursor: null }
