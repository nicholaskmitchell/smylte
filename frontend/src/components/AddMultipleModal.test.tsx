import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AddMultipleModal, bodyFrom, splitPasteLines } from './AddMultipleModal'
import type { CreateTaskBody, List } from '../api'

const mkList = (id: string, name: string): List => ({
  id, href: `/${id}/`, name, is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
})
const LISTS = [mkList('l1', 'Work'), mkList('l2', 'Home')]

type Item = { listId: string; body: CreateTaskBody }

/** Render with a resolved-by-default onSubmit; returns the spies. */
function setup(failures: number[] = []) {
  const onSubmit = vi.fn<(items: Item[], p: (n: number) => void) => Promise<number[]>>(
    async () => failures)
  const onClose = vi.fn()
  render(<AddMultipleModal lists={LISTS} defaultList="l1" onSubmit={onSubmit} onClose={onClose} />)
  return { onSubmit, onClose, user: userEvent.setup() }
}

const title = (n: number) => screen.getByLabelText(`Title, row ${n}`)
const add = () => screen.getByRole('button', { name: /^Add \d+ task|^Add tasks$/ })
const itemsOf = (onSubmit: { mock: { calls: [Item[], unknown][] } }) => onSubmit.mock.calls[0][0]

describe('splitPasteLines', () => {
  it('splits on every newline flavour and drops blanks', () => {
    expect(splitPasteLines('a\r\nb\rc\n\n d ')).toEqual(['a', 'b', 'c', 'd'])
  })

  it('strips the list markers you get pasting out of a doc', () => {
    expect(splitPasteLines('- one\n* two\n3) three\n4. four\n• five'))
      .toEqual(['one', 'two', 'three', 'four', 'five'])
  })

  it('leaves a hyphen that is part of the title alone', () => {
    expect(splitPasteLines('e-mail the vendor')).toEqual(['e-mail the vendor'])
  })
})

describe('bodyFrom', () => {
  const v = {
    listId: 'l1', dueDate: '', dueTime: '', startDate: '', startTime: '',
    priority: 'none', tags: [], notes: '',
  }

  it('omits every empty field rather than sending it blank', () => {
    expect(bodyFrom('Ship it', v)).toEqual({ summary: 'Ship it' })
  })

  it('sends a bare date for an all-day due and a T-joined one when timed', () => {
    expect(bodyFrom('x', { ...v, dueDate: '2026-08-10' }).due).toBe('2026-08-10')
    expect(bodyFrom('x', { ...v, dueDate: '2026-08-10', dueTime: '09:30' }).due)
      .toBe('2026-08-10T09:30')
  })

  it('drops a time with no date', () => {
    expect(bodyFrom('x', { ...v, dueTime: '09:30' }).due).toBeUndefined()
  })

  it('carries the tag list through verbatim', () => {
    expect(bodyFrom('x', { ...v, tags: ['a', 'b'] }).tags).toEqual(['a', 'b'])
    // A category may contain a comma; it must survive as one tag.
    expect(bodyFrom('x', { ...v, tags: ['Home,Garden'] }).tags).toEqual(['Home,Garden'])
    expect(bodyFrom('x', { ...v, tags: [] }).tags).toBeUndefined()
  })

  it('sends a bare date for an all-day start and a T-joined one when timed', () => {
    // A task's DTSTART can be timed, and other CalDAV clients write one; with a
    // date-only control the time had nowhere to live.
    expect(bodyFrom('x', { ...v, startDate: '2026-08-10' }).start).toBe('2026-08-10')
    expect(bodyFrom('x', { ...v, startDate: '2026-08-10', startTime: '14:30' }).start)
      .toBe('2026-08-10T14:30')
    expect(bodyFrom('x', { ...v, startTime: '14:30' }).start).toBeUndefined()
  })
})

describe('AddMultipleModal', () => {
  it('opens with blank rows, every property shared, and nothing to add', () => {
    setup()
    expect(screen.getByRole('dialog', { name: /add multiple tasks/i })).toBeInTheDocument()
    expect(title(3)).toBeInTheDocument()
    // Shared strip owns one control per property; rows carry none of them.
    expect(screen.getByLabelText('List, for all tasks')).toBeInTheDocument()
    expect(screen.getByLabelText('Due date, for all tasks')).toBeInTheDocument()
    expect(screen.queryByLabelText('Due date, row 1')).not.toBeInTheDocument()
    expect(add()).toBeDisabled()
  })

  it('follows the app\'s modal conventions', () => {
    setup()
    // A plain labelled field, like Scheduling's "Weekly availability" — the
    // shared controls are not fenced off in a panel of their own.
    expect(screen.getByText('Same for all')).toBeInTheDocument()
    // Row-adding uses the app's dashed "+ noun" affordance.
    expect(screen.getByRole('button', { name: '+ row' })).toBeInTheDocument()
    // No modal in this app has a Cancel button — ✕, Escape and the backdrop
    // are how you leave.
    expect(screen.queryByRole('button', { name: /cancel/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('sends only the rows with a title, in order', async () => {
    const { onSubmit, user } = setup()
    await user.type(title(1), 'first')
    await user.type(title(3), 'third')
    await user.click(add())
    expect(itemsOf(onSubmit).map((i) => i.body.summary)).toEqual(['first', 'third'])
  })

  it('applies shared values to every task and omits the untouched ones', async () => {
    const { onSubmit, user } = setup()
    await user.selectOptions(screen.getByLabelText('List, for all tasks'), 'l2')
    await user.selectOptions(screen.getByLabelText('Priority, for all tasks'), 'high')
    await user.type(screen.getByLabelText('Due date, for all tasks'), '2026-08-10')
    await user.type(title(1), 'a')
    await user.type(title(2), 'b')
    await user.click(add())
    expect(itemsOf(onSubmit).map(({ listId, body }) => ({ listId, body }))).toEqual([
      { listId: 'l2', body: { summary: 'a', priority: 'high', due: '2026-08-10' } },
      { listId: 'l2', body: { summary: 'b', priority: 'high', due: '2026-08-10' } },
    ])
  })

  it('keeps the due time disabled until a date exists', async () => {
    const { user } = setup()
    expect(screen.getByLabelText('Due time, for all tasks')).toBeDisabled()
    await user.type(screen.getByLabelText('Due date, for all tasks'), '2026-08-10')
    expect(screen.getByLabelText('Due time, for all tasks')).toBeEnabled()
  })

  it('unticking a property moves it out of the strip and into every row', async () => {
    const { onSubmit, user } = setup()
    await user.click(screen.getByRole('checkbox', { name: 'Priority' }))
    expect(screen.queryByLabelText('Priority, for all tasks')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Priority, row 1')).toBeInTheDocument()

    await user.type(title(1), 'a')
    await user.type(title(2), 'b')
    await user.selectOptions(screen.getByLabelText('Priority, row 1'), 'high')
    await user.click(add())
    const items = itemsOf(onSubmit)
    expect(items[0].body.priority).toBe('high')
    expect(items[1].body).not.toHaveProperty('priority')
  })

  it('adopts a value already typed per-row when the property becomes shared', async () => {
    const { onSubmit, user } = setup()
    await user.click(screen.getByRole('checkbox', { name: 'Due' }))
    await user.type(screen.getByLabelText('Due date, row 1'), '2026-08-10')
    await user.click(screen.getByRole('checkbox', { name: 'Due' }))
    // The date the user typed is now the shared one, not silently lost.
    expect(screen.getByLabelText('Due date, for all tasks')).toHaveValue('2026-08-10')

    await user.type(title(1), 'a')
    await user.type(title(2), 'b')
    await user.click(add())
    expect(itemsOf(onSubmit).map((i) => i.body.due)).toEqual(['2026-08-10', '2026-08-10'])
  })

  it('restores per-row values when a property goes back to per-row', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('checkbox', { name: 'Tags' }))
    await user.type(screen.getByLabelText('Tags, row 2'), 'errand{Enter}')
    await user.click(screen.getByRole('checkbox', { name: 'Tags' }))
    await user.click(screen.getByRole('checkbox', { name: 'Tags' }))
    expect(screen.getByRole('button', { name: 'Remove errand' })).toBeInTheDocument()
  })

  it('fans a multi-line paste out into one row per line', async () => {
    const { user } = setup()
    await user.click(title(1))
    await user.paste('alpha\nbravo\ncharlie\ndelta')
    expect(title(1)).toHaveValue('alpha')
    expect(title(4)).toHaveValue('delta')
    expect(screen.queryByLabelText('Title, row 5')).not.toBeInTheDocument()
  })

  it('fills forward from the pasted row', async () => {
    const { user } = setup()
    await user.type(title(1), 'kept')
    await user.click(title(2))
    await user.paste('one\ntwo\nthree')
    expect(title(1)).toHaveValue('kept')
    expect(title(2)).toHaveValue('one')
    expect(title(4)).toHaveValue('three')
  })

  it('leaves a single-line paste to the browser', async () => {
    const { user } = setup()
    await user.click(title(1))
    await user.paste('just one')
    expect(title(1)).toHaveValue('just one')
    expect(screen.queryByLabelText('Title, row 4')).not.toBeInTheDocument()
  })

  it('adds a row on Enter and keeps the rows around it intact', async () => {
    const { user } = setup()
    await user.type(title(1), 'first')
    await user.type(title(3), 'third')
    await user.type(title(1), '{Enter}')
    expect(title(1)).toHaveValue('first')
    expect(title(2)).toHaveValue('')        // the new row landed directly below
    expect(title(4)).toHaveValue('third')
  })

  it('removes a row by its ✕ without disturbing the others', async () => {
    const { user } = setup()
    await user.type(title(1), 'first')
    await user.type(title(3), 'third')
    await user.click(screen.getByRole('button', { name: 'Remove row 2' }))
    expect(title(1)).toHaveValue('first')
    expect(title(2)).toHaveValue('third')
  })

  it('closes once every task lands', async () => {
    const { onClose, user } = setup()
    await user.type(title(1), 'a')
    await user.click(add())
    expect(onClose).toHaveBeenCalled()
  })

  it('stays open on a partial failure, keeping only the rows that failed', async () => {
    const { onClose, user } = setup([1])
    await user.type(title(1), 'landed')
    await user.type(title(2), 'failed')
    await user.click(add())

    expect(onClose).not.toHaveBeenCalled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/1 task couldn't be created/)
    expect(title(1)).toHaveValue('failed')
    expect(screen.queryByDisplayValue('landed')).not.toBeInTheDocument()
    expect(add()).toHaveTextContent('Add 1 task')
  })

  it('blocks input and dismissal while the batch is in flight', async () => {
    let release: (v: number[]) => void = () => {}
    const onSubmit = vi.fn(() => new Promise<number[]>((r) => { release = r }))
    const onClose = vi.fn()
    render(<AddMultipleModal lists={LISTS} defaultList="l1" onSubmit={onSubmit} onClose={onClose} />)
    const user = userEvent.setup()

    await user.type(title(1), 'a')
    await user.click(screen.getByRole('button', { name: 'Add 1 task' }))

    expect(screen.getByRole('button', { name: 'Adding…' })).toBeDisabled()
    expect(title(1)).toBeDisabled()
    await user.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()

    release([])
    await screen.findByRole('button', { name: 'Add 1 task' })
    expect(onClose).toHaveBeenCalled()
  })
})
