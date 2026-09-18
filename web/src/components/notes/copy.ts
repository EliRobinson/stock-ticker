// Every user-facing string on the Notes screen.
// Chrome copy: the fact, then the consequence, then the action (AGENTS.md).

export const notesCopy = {
  title: 'Notes',
  count: (total: number, shown: number) =>
    total === shown ? `${total} Notes` : `${total} Notes · ${shown} shown`,
  newNote: 'New Note',
  companyFilter: 'Company filter',
  allCompanies: 'All Companies',
  wholeMarket: 'Whole market',
  anyDate: 'Any date',
  dateFilter: 'Date range filter',
  clearDates: 'Clear dates',
  search: 'Search Note text',
  loading: 'Loading Notes…',
  emptyTitle: 'No Notes yet',
  emptyBody: 'Click “New Note” to write one.',
  noMatchTitle: 'No Notes match these filters',
  noMatchBody: 'Clear the filters to see all Notes.',
  clearFilters: 'Clear filters',
  errorTitle: 'Notes are unavailable',
  errorBody:
    'The database connection failed. Nothing can be created or edited until it recovers.',
  actions: 'Note actions',
  edit: 'Edit',
  delete: 'Delete',
  deleted: 'Note deleted.',
  undo: 'Undo',
  undoFailed: 'The Note was not restored. Try Undo again.',
  deleteFailed: 'The Note was not deleted. The database connection failed.',
  readMore: 'Read more',
  showLess: 'Show less',
  singleDate: 'single date',
  range: 'range'
} as const
