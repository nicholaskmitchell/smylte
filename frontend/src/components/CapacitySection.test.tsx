// What the day-capacity section is for, asserted.
//
// The section shipped with 127 lines and no test file at all, and four
// independent mutations of it survived the whole suite — which is another way
// of saying nothing here was true on purpose. It delegates its PARSING to
// `capacity.ts`, and `capacity.test.ts` already walks every spelling through
// `parseCapacity`/`capacityInput`, so nothing below re-tests the parser. What is
// pinned here is the part only the component owns: when a field commits, when it
// clears, when it refuses, and what an unset weekday says.
//
// `TabsSection.test.tsx` is the template — the same `show()` helper, no API mock
// and no provider, because a controlled section takes props and hands changes
// back and has no business fetching anything.

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CapacitySection } from './CapacitySection'

function show(minutes: number | null = null, byWeekday: Record<string, number> = {}) {
  const onChange = vi.fn()
  const onWeekdayChange = vi.fn()
  render(<CapacitySection minutes={minutes} byWeekday={byWeekday}
    onChange={onChange} onWeekdayChange={onWeekdayChange} />)
  return { onChange, onWeekdayChange }
}

const dflt = () => screen.getByLabelText('Working time for the default working day')
const sunday = () => screen.getByLabelText('Working time for Sun')

/** Type into a field and commit it the way a person leaves one: by tabbing out.
 *  Blur is the commit everywhere in this component, so a test that only typed
 *  would assert nothing. */
async function commit(field: HTMLElement, text: string) {
  await userEvent.clear(field)
  if (text) await userEvent.type(field, text)
  await userEvent.tab()
}

describe('<CapacitySection>', () => {
  it('shows the stored value the way a person would say it', () => {
    show(300, { sun: 0, wed: 90 })
    expect(dflt()).toHaveValue('5h')
    expect(sunday()).toHaveValue('0m')
    expect(screen.getByLabelText('Working time for Wed')).toHaveValue('1h 30m')
  })

  it('says an unset weekday INHERITS rather than showing zero', () => {
    // These are different statements — "same as most days" and "I do not work
    // Sundays" — and a zero standing in for silence would make the second
    // unsayable. The placeholder is the only thing that keeps them apart.
    show(300, {})
    expect(sunday()).toHaveValue('')
    expect(sunday()).toHaveAttribute('placeholder', 'same as most days')

    // ...and a deliberate zero is a VALUE, not a placeholder.
    show(300, { sun: 0 })
    expect(screen.getAllByLabelText('Working time for Sun')[1]).toHaveValue('0m')
  })

  it('commits a typed length in either spelling', async () => {
    const { onChange } = show(null)
    await commit(dflt(), '300')
    expect(onChange).toHaveBeenCalledWith(300)

    const second = show(null)
    await commit(screen.getAllByLabelText('Working time for the default working day')[1], '5h')
    expect(second.onChange).toHaveBeenCalledWith(300)
  })

  it('clears an emptied field, which is the only way back to "never said"', async () => {
    const { onChange } = show(300)
    await commit(dflt(), '')
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('does not write when there was nothing to clear', async () => {
    // An empty field blurred on a value that is already unset is a no-op, not a
    // clear — otherwise merely tabbing through Settings would write every field.
    const { onChange } = show(null)
    await commit(dflt(), '')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('does not write when the typed value is what is already stored', async () => {
    const { onChange } = show(300)
    await commit(dflt(), '5h')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('SNAPS BACK on a line it cannot read, rather than clearing', async () => {
    // The one outcome worse than doing nothing would be silently deleting a
    // setting the owner was in the middle of editing. So an unreadable line
    // restores the stored value and writes nothing at all.
    const { onChange } = show(300)
    await commit(dflt(), 'soon')
    expect(onChange).not.toHaveBeenCalled()
    expect(dflt()).toHaveValue('5h')
  })

  it('rebuilds the whole weekday map to change one day', async () => {
    // Read-modify-write, which is why `day_capacity_by_weekday` has to be on
    // App's MERGED_SETTINGS: the section hands back the entire object, so a
    // write that lost the rest would drop every other weekday.
    const { onWeekdayChange } = show(300, { mon: 240, fri: 180 })
    await commit(sunday(), '2h')
    expect(onWeekdayChange).toHaveBeenCalledWith({ mon: 240, fri: 180, sun: 120 })
  })

  it('DELETES a weekday key rather than storing zero when it is emptied', async () => {
    // Clearing a weekday means "fall through to the default" — a different
    // statement from "I do not work then", which is what a stored 0 says.
    const { onWeekdayChange } = show(300, { sun: 120, mon: 240 })
    await commit(sunday(), '')
    expect(onWeekdayChange).toHaveBeenCalledWith({ mon: 240 })
  })

  it('keeps a deliberate zero as a value', async () => {
    const { onWeekdayChange } = show(300, {})
    await commit(sunday(), '0')
    expect(onWeekdayChange).toHaveBeenCalledWith({ sun: 0 })
  })

  it('abandons an edit on Escape WITHOUT closing the settings sheet', async () => {
    // `useEscape` is bound to the window, so without the propagation stop the
    // panel would close out from under a half-typed number. The section is a
    // body inside that panel and does not own the way out.
    // Escape only — typing into the field fires keydowns of its own, and
    // counting those would make this assert nothing about Escape at all.
    const onWindowEscape = vi.fn()
    const listener = (e: KeyboardEvent) => { if (e.key === 'Escape') onWindowEscape() }
    window.addEventListener('keydown', listener)
    try {
      const { onChange } = show(300)
      await userEvent.clear(dflt())
      await userEvent.type(dflt(), '99')
      await userEvent.keyboard('{Escape}')
      expect(dflt()).toHaveValue('5h')
      expect(onChange).not.toHaveBeenCalled()
      expect(onWindowEscape).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('keydown', listener)
    }
  })

  it('follows the value when it changes underneath', async () => {
    // A rejected settings write leaves the old number in place, and another
    // device can change it — so a stale draft must not be committed over a
    // newer value on the next blur.
    const view = render(<CapacitySection minutes={300} byWeekday={{}}
      onChange={vi.fn()} onWeekdayChange={vi.fn()} />)
    await userEvent.clear(dflt())
    await userEvent.type(dflt(), '99')
    view.rerender(<CapacitySection minutes={180} byWeekday={{}}
      onChange={vi.fn()} onWeekdayChange={vi.fn()} />)
    expect(dflt()).toHaveValue('3h')
  })
})
