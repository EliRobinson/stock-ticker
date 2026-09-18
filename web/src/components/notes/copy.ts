import { sharedCopy } from '../shared/copy'

// Every user-facing string on the Notes screen and the Note dialog.
// Chrome copy: the fact, then the consequence, then the action (AGENTS.md).

export const notesCopy = {
  title: 'Notes',
  count: (total: number, shown: number) =>
    total === shown ? `${total} Notes` : `${total} Notes · ${shown} shown`,
  newNote: sharedCopy.newNote,
  companyFilter: 'Company filter',
  allCompanies: 'All Companies',
  wholeMarket: sharedCopy.wholeMarket,
  anyDate: 'Any date',
  dateFilter: 'Date range filter',
  clearDates: 'Clear dates',
  search: 'Search Note text',
  loading: 'Loading Notes…',
  emptyTitle: 'No Notes yet',
  emptyBody: 'Click “New Note” to write one.',
  noMatchTitle: 'No Notes match these filters',
  noMatchBody: 'Clear the filters to see all Notes.',
  errorTitle: 'Notes are unavailable',
  errorBody:
    'The database connection failed. Nothing can be created or edited until it recovers.',
  actions: 'Note actions',
  edit: 'Edit',
  delete: 'Delete',
  deleted: 'Note deleted.',
  undo: 'Undo',
  undoFailed: 'The Note was not restored. Try Undo again.',
  deleteFailed: 'The Note was not deleted. The database connection failed.'
} as const

export const noteDialogCopy = {
  newTitle: sharedCopy.newNote,
  editTitle: 'Edit Note',
  close: 'Close',
  company: 'Company',
  wholeMarket: sharedCopy.wholeMarket,
  start: 'Date',
  end: 'End date (optional)',
  pickDate: 'Pick a date',
  fromRange: 'from the dragged range',
  fromDate: 'from the chart',
  body: 'Body · markdown',
  cancel: 'Cancel',
  save: 'Save Note',
  saving: 'Saving…',
  errors: {
    bodyEmpty: 'Write the Note before saving.',
    bodyLong: 'Notes are capped at 10,000 characters. Shorten this one.',
    startMissing: 'Pick a date.',
    endBefore: 'The end date is before the start date. Pick a later end date.',
    outOfRange:
      'Dates run from 1 Jan 1990 to one year from today. Pick a date in that span.'
  },
  saveFailed:
    'The Note was not saved. The database connection failed. Try again.'
} as const
