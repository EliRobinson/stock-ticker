import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { NoteForm, validateNote } from '@/components/notes/note-dialog'

import { installBrowserMocks } from './browser-mocks'

const TODAY = '2024-09-17'

describe('Note form', () => {
  afterEach(cleanup)
  beforeAll(installBrowserMocks)

  it('blocks an empty body and says what to do', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(
      <NoteForm
        inDialog={false}
        initial={{ cik: null, start_date: TODAY, end_date: '', body: '   ' }}
        today={TODAY}
        onSave={onSave}
        onCancel={() => {}}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Save Note' }))
    expect(
      await screen.findByText('Write the Note before saving.')
    ).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /body/i })).toHaveAttribute(
      'aria-invalid',
      'true'
    )
    expect(onSave).not.toHaveBeenCalled()
  })

  it('saves a trimmed body and defaults the end date to the start date', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(
      <NoteForm
        inDialog={false}
        initial={{
          cik: '0000320193',
          start_date: '2024-08-05',
          end_date: '',
          body: ''
        }}
        today={TODAY}
        onSave={onSave}
        onCancel={() => {}}
        lockCompany
        companies={[{ cik: '0000320193', label: 'AAPL · Apple Inc.' }]}
      />
    )
    await user.type(
      screen.getByRole('textbox', { name: /body/i }),
      '  Positioning unwind.  '
    )
    await user.click(screen.getByRole('button', { name: 'Save Note' }))
    expect(onSave).toHaveBeenCalledWith({
      cik: '0000320193',
      start_date: '2024-08-05',
      end_date: '2024-08-05',
      body: 'Positioning unwind.'
    })
  })

  it.each([
    [
      { start_date: '2024-09-12', end_date: '2024-08-05' },
      'end_date',
      'The end date is before the start date. Pick a later end date.'
    ],
    [
      { start_date: '1989-12-31', end_date: '' },
      'start_date',
      'Dates run from 1 Jan 1990 to one year from today. Pick a date in that span.'
    ],
    [{ start_date: '', end_date: '' }, 'start_date', 'Pick a date.']
  ])('rejects %o', (dates, field, message) => {
    const errors = validateNote({ cik: null, body: 'x', ...dates }, TODAY)
    expect(errors[field as keyof typeof errors]).toBe(message)
  })

  it('caps the body at 10,000 characters', () => {
    const errors = validateNote(
      { cik: null, start_date: TODAY, end_date: '', body: 'a'.repeat(10_001) },
      TODAY
    )
    expect(errors.body).toMatch(/10,000/)
  })
})
