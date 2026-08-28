// Tapping a date or time field opens the device's own picker.
//
// Two halves, and the second is the one that keeps the first true. The
// behavioural cases pin what `DateTimeInput` does — including the three ways
// `showPicker` can be unavailable, each of which must leave an ordinary,
// perfectly usable native input behind. The structural case pins that every
// date and time field in the app goes through it, by reading the component
// sources: a rule that lives in one component and is applied by remembering to
// import it is a rule with a half-life. Same shape, and the same reason, as
// `modal-contract.test.tsx`.

import { describe, expect, it, vi, afterEach } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DateTimeInput } from './components/DateTimeInput'

/** jsdom implements no picker at all, so every test here installs its own and
 *  puts the prototype back afterwards. That absence is itself a case — see
 *  "survives a browser that has never heard of showPicker". */
type WithPicker = { showPicker?: () => void }

function stubPicker(impl: () => void = () => {}) {
  const proto = HTMLInputElement.prototype as unknown as WithPicker
  const had = Object.prototype.hasOwnProperty.call(proto, 'showPicker')
  const prior = proto.showPicker
  const spy = vi.fn(impl)
  proto.showPicker = spy
  return {
    spy,
    restore: () => {
      if (had) proto.showPicker = prior
      else delete proto.showPicker
    },
  }
}

let undo: (() => void) | null = null
afterEach(() => { undo?.(); undo = null; cleanup() })

describe('<DateTimeInput>', () => {
  it('opens the picker when the field itself is clicked', async () => {
    // The whole point. In Chrome and Edge — Android included — a click on the
    // field puts a caret in a segment and shows nothing; only the few-millimetre
    // indicator glyph opens the calendar.
    const { spy, restore } = stubPicker()
    undo = restore
    const user = userEvent.setup()
    render(<DateTimeInput type="date" aria-label="Due date" defaultValue="2026-08-28" />)

    await user.click(screen.getByLabelText('Due date'))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('leaves the field a field: typing and the caller\'s onChange are untouched', () => {
    const { restore } = stubPicker()
    undo = restore
    const onChange = vi.fn()
    render(<DateTimeInput type="date" aria-label="Due date" value="" onChange={onChange} />)

    const el = screen.getByLabelText('Due date')
    fireEvent.change(el, { target: { value: '2026-08-28' } })
    expect(onChange).toHaveBeenCalledTimes(1)
    // Forwarded untouched, so a call site reads exactly as it did as a bare
    // input — this one is a controlled field and stays one.
    expect(el).toHaveAttribute('type', 'date')
  })

  it('still runs a caller\'s own onClick', () => {
    const { spy, restore } = stubPicker()
    undo = restore
    const onClick = vi.fn()
    render(<DateTimeInput type="time" aria-label="Due time" onClick={onClick} />)

    fireEvent.click(screen.getByLabelText('Due time'))
    expect(spy).toHaveBeenCalledTimes(1)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('does NOT open on focus alone', async () => {
    // Reaching a field with Tab is not asking for a popup over it, and a
    // keyboard user who wants one already has Alt+Down and F4. Binding this to
    // focus would also fire on every programmatic focus in the app.
    const { spy, restore } = stubPicker()
    undo = restore
    const user = userEvent.setup()
    render(
      <>
        <button>before</button>
        <DateTimeInput type="date" aria-label="Due date" />
      </>,
    )

    screen.getByRole('button').focus()
    await user.tab()
    expect(screen.getByLabelText('Due date')).toHaveFocus()
    expect(spy).not.toHaveBeenCalled()
  })

  it('survives a browser that has never heard of showPicker', () => {
    // jsdom is that browser, so this is the default state — asserted rather
    // than assumed, because an optional call is one refactor from a bare one.
    const proto = HTMLInputElement.prototype as unknown as WithPicker
    expect(proto.showPicker).toBeUndefined()
    render(<DateTimeInput type="date" aria-label="Due date" />)
    expect(() => fireEvent.click(screen.getByLabelText('Due date'))).not.toThrow()
  })

  it('survives a picker that refuses', () => {
    // `showPicker` throws NotAllowedError without transient user activation and
    // InvalidStateError for an input type that has no picker. In both cases the
    // field behaves exactly as it did before this component existed, so there
    // is nothing to report and nothing to fall back to.
    const { spy, restore } = stubPicker(() => { throw new Error('NotAllowedError') })
    undo = restore
    const onChange = vi.fn()
    render(<DateTimeInput type="date" aria-label="Due date" value="" onChange={onChange} />)

    const el = screen.getByLabelText('Due date')
    expect(() => fireEvent.click(el)).not.toThrow()
    expect(spy).toHaveBeenCalled()
    // …and the field still takes a value afterwards.
    fireEvent.change(el, { target: { value: '2026-08-28' } })
    expect(onChange).toHaveBeenCalledTimes(1)
  })
})

// ── every date field in the app goes through it ────────────────────────────

const sources = (import.meta as unknown as {
  glob: (p: string, o: object) => Record<string, () => Promise<string>>
}).glob('./**/*.tsx', { query: '?raw', import: 'default' })

/** Source with comments removed, so prose ABOUT a date input is not read as
 *  one. `DateTimeInput.tsx`'s own header quotes the markup it replaces.
 *
 *  The glob is the WHOLE src tree, not just `components/`, because that is
 *  where the rule has to hold — a date field added to `App.tsx` is as much a
 *  date field as one added beside the others. */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n').filter((l) => !/^\s*(\/\/|\*)/.test(l)).join('\n')
}

/** A `type=` naming one of the three pickered input types, in either the
 *  string form (`type="date"`) or the expression form the event editor needs
 *  (`type={allDay ? 'date' : 'datetime-local'}`). */
const DATE_TYPE = /type=(?:"(?:date|time|datetime-local)"|\{[^}]*'(?:date|time|datetime-local)'[^}]*\})/g

/** The element each of those `type=`s belongs to.
 *
 *  Found by walking BACK to the nearest `<`, rather than by matching a whole
 *  JSX tag: an attribute value here routinely contains `>` (`onChange={(e) =>
 *  …}`), so `<input[^>]*>` stops in the middle of the element and reads the
 *  next one's attributes as this one's. */
function pickeredTags(src: string): string[] {
  const out: string[] = []
  for (const m of src.matchAll(DATE_TYPE)) {
    const open = src.lastIndexOf('<', m.index)
    if (open < 0) continue
    out.push(src.slice(open + 1).match(/^[A-Za-z][\w.]*/)?.[0] ?? '')
  }
  return out
}

describe('every date and time field', () => {
  it('is a DateTimeInput, not a bare input', async () => {
    const offenders: string[] = []
    let found = 0
    for (const [path, load] of Object.entries(sources)) {
      // The component itself is the one place a bare input belongs — it is what
      // it renders. Its own test file is not a component.
      if (/\.test\.tsx$/.test(path) || /DateTimeInput\.tsx$/.test(path)) continue
      for (const tag of pickeredTags(code(await load()))) {
        found += 1
        if (tag !== 'DateTimeInput') offenders.push(`${path}: <${tag}>`)
      }
    }
    expect(offenders).toEqual([])
    // The scan really did find the app's date fields — otherwise a regex that
    // matched nothing would pass this test for the wrong reason, every time.
    expect(found).toBeGreaterThanOrEqual(9)
  })

  it('finds a bare input when there is one', () => {
    // The guard, guarded. `pickeredTags` is the whole of the check above, so a
    // change that quietly stopped it from resolving an element would take the
    // check with it and nothing would fail.
    expect(pickeredTags('<input className="input" type="date" value={v} />'))
      .toEqual(['input'])
    expect(pickeredTags("<DateTimeInput type={allDay ? 'date' : 'datetime-local'} />"))
      .toEqual(['DateTimeInput'])
    // The `>` inside an attribute that a whole-tag regex would trip on.
    expect(pickeredTags('<input onChange={(e) => set(e)} type="time" />')).toEqual(['input'])
  })
})
