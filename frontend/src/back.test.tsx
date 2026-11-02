// Android's Back, from the host's `back` event down to the dialogs (layers.ts),
// through the real android.ts and the real layer stack. The per-component Back
// cases sit beside each component's Escape cases; this file is the path the
// host takes, and the forms that ask before they discard.
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AddMultipleModal } from './components/AddMultipleModal'
import { AppearancePanel } from './components/AppearancePanel'
import { DayPopover } from './components/DayPopover'
import { TaskModal } from './components/TaskModal'
import { startAndroidHost } from './android'
import { withPrompt } from './test/back'
import type { Appearance, CustomTheme } from './appearance'
import type { List, Task } from './api'

const layers = vi.fn()

beforeAll(() => {
  vi.stubGlobal('SmylteAndroid', { layers })
  startAndroidHost()
})
afterAll(() => {
  vi.unstubAllGlobals()
})
beforeEach(() => layers.mockClear())

/** The host's Back: the real event, the way evaluateJavascript delivers it. */
const back = () => act(() => {
  window.dispatchEvent(new CustomEvent('smylte-android', { detail: { type: 'back' } }))
})
const flush = () => act(async () => { await Promise.resolve() })

// ── fixtures ───────────────────────────────────────────────────────────────

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, parked: false, parked_at: null,
  original_due: null, original_due_is_date: false, original_due_moved: false,
  priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const lists: List[] = [{
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
}]

function taskModal(t: Task | null, initialTitle?: string) {
  const spies = {
    onClose: vi.fn(), onCreate: vi.fn(), onSave: vi.fn(),
    onDelete: vi.fn(), onMultiple: vi.fn(),
  }
  const view = render(withPrompt(
    <TaskModal task={t} lists={lists} defaultList="l1" initialTitle={initialTitle} {...spies} />))
  return { ...spies, ...view }
}

const prompt = () => screen.queryByRole('alertdialog', { name: 'Discard changes?' })

describe('Back in the task form', () => {
  it('closes an untouched editor at once, with no question', () => {
    const { onClose } = taskModal(task())
    back()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(prompt()).toBeNull()
  })

  it('asks about an edited title, keeps editing on a second Back, and discards on request', async () => {
    const { onClose, onSave } = taskModal(task())
    const title = screen.getByLabelText('Title')
    await userEvent.type(title, '!')
    back()
    expect(prompt()).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()

    back()
    expect(prompt()).toBeNull()
    expect(onClose).not.toHaveBeenCalled()
    expect(title).toHaveValue('Ship it!')

    back()
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onSave).not.toHaveBeenCalled()
  })

  it('asks when creating with a title handed over, and closes when creating blank', () => {
    const handed = taskModal(null, 'Buy milk')
    back()
    expect(prompt()).toBeInTheDocument()
    expect(handed.onClose).not.toHaveBeenCalled()
    handed.unmount()

    const blank = taskModal(null)
    back()
    expect(prompt()).toBeNull()
    expect(blank.onClose).toHaveBeenCalledTimes(1)
  })

  it('leaves Escape as it was: it closes an edited form at once', async () => {
    const { onClose } = taskModal(task())
    await userEvent.type(screen.getByLabelText('Title'), '!')
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(prompt()).toBeNull()
  })
})

describe('Back and the host\'s layer count', () => {
  it('is told 1 once the modal is open and 0 once it has closed', async () => {
    const { unmount } = taskModal(task())
    await flush()
    expect(layers).toHaveBeenLastCalledWith(1)
    unmount()
    await flush()
    expect(layers).toHaveBeenLastCalledWith(0)
  })

  it('tells the host nothing is open when Back finds nothing', () => {
    back()
    expect(layers).toHaveBeenCalledWith(0)
  })
})

describe('Back in the bulk composer', () => {
  const composer = (initialTitle?: string) => {
    const onClose = vi.fn()
    render(withPrompt(
      <AddMultipleModal lists={lists} defaultList="l1" initialTitle={initialTitle}
        onSubmit={async () => []} onClose={onClose} />))
    return { onClose }
  }

  it('closes the blank rows it opens with', () => {
    const { onClose } = composer()
    back()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(prompt()).toBeNull()
  })

  it('asks about a typed row', async () => {
    const { onClose } = composer()
    await userEvent.type(screen.getAllByPlaceholderText(/./)[0]!, 'Milk')
    back()
    expect(prompt()).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('Back in the appearance panel', () => {
  const mine: CustomTheme = {
    id: 't1', name: 'Mine', base: 'light', light: { '--accent': '#ff0000' }, dark: {},
  }
  const panel = () => {
    const onClose = vi.fn()
    const appearance: Appearance = { active: 't1', themes: [mine] }
    render(withPrompt(
      <AppearancePanel appearance={appearance} onChange={vi.fn()} mode="light"
        onMode={vi.fn()} onClose={onClose} />))
    return { onClose }
  }

  it('asks when the rename row holds a changed name', async () => {
    const { onClose } = panel()
    await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
    await userEvent.type(screen.getByLabelText('Theme name'), '!')
    back()
    expect(prompt()).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('closes when there is no rename row', () => {
    const { onClose } = panel()
    back()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(prompt()).toBeNull()
  })

  it('closes when the rename row is open but its name is unchanged', async () => {
    const { onClose } = panel()
    await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
    back()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(prompt()).toBeNull()
  })
})

describe('Back on a day popover', () => {
  it('closes it', () => {
    const onClose = vi.fn()
    render(<DayPopover day="2026-08-03" x={40} y={40} events={[]}
      styleOf={() => undefined} onClose={onClose} />)
    back()
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
