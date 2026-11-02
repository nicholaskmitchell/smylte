import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { StrictMode, useRef, useState, type ReactNode } from 'react'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SHIELD_MS } from './components/DiscardPrompt'
import { useEscape } from './hooks'
import {
  backTopLayer, layerDepth, onLayerDepth, PendingWrite, UnsentInput, useDiscardAsk, useLayer,
  usePending, usePendingCount, useUnsent, useUnsentCount,
} from './layers'
import { pressBack, withPrompt } from './test/back'

afterEach(cleanup)

function Layer({ onBack, name, ...options }: {
  onBack: () => void
  name?: string
  open?: boolean
  unsaved?: boolean
  busy?: boolean
  children?: ReactNode
}) {
  useLayer(onBack, { open: options.open, unsaved: options.unsaved, busy: options.busy })
  return <div data-testid={name}>{options.children}</div>
}

/** A layer with a text field and an `useEscape`, like an editor. */
function Editor({ onBack, onClose, unsaved = true }: {
  onBack: () => void
  onClose?: () => void
  unsaved?: boolean
}) {
  useLayer(onBack, { unsaved })
  useEscape(onClose ?? onBack)
  return <input aria-label="title" />
}

describe('layers: order', () => {
  it('puts a child mounted in the same commit above its parent', () => {
    const parent = vi.fn()
    const child = vi.fn()
    render(<Layer onBack={parent}><Layer onBack={child} /></Layer>)
    expect(layerDepth()).toBe(2)
    pressBack()
    expect(child).toHaveBeenCalledTimes(1)
    expect(parent).not.toHaveBeenCalled()
  })

  it('orders flag-opened layers by when they opened', () => {
    const first = vi.fn()
    const second = vi.fn()
    // The second is the earlier sibling in the tree, but opens later.
    const { rerender } = render(<>
      <Layer onBack={second} open={false} />
      <Layer onBack={first} open />
    </>)
    rerender(<>
      <Layer onBack={second} open />
      <Layer onBack={first} open />
    </>)
    pressBack()
    expect(second).toHaveBeenCalledTimes(1)
    expect(first).not.toHaveBeenCalled()
  })

  it('calls the latest handler', () => {
    const old = vi.fn()
    const latest = vi.fn()
    const { rerender } = render(<Layer onBack={old} />)
    rerender(<Layer onBack={latest} />)
    pressBack()
    expect(latest).toHaveBeenCalledTimes(1)
    expect(old).not.toHaveBeenCalled()
  })
})

describe('layers: depth', () => {
  it('forgets a layer that unmounts or closes its flag', () => {
    const { rerender, unmount } = render(<Layer onBack={() => {}} open />)
    expect(layerDepth()).toBe(1)
    rerender(<Layer onBack={() => {}} open={false} />)
    expect(layerDepth()).toBe(0)
    expect(pressBack()).toBe(false)
    rerender(<Layer onBack={() => {}} open />)
    expect(layerDepth()).toBe(1)
    unmount()
    expect(layerDepth()).toBe(0)
    expect(backTopLayer()).toBe(false)
  })

  it('reports each depth change', () => {
    const seen: number[] = []
    const off = onLayerDepth((n) => seen.push(n))
    const one = render(<Layer onBack={() => {}} />)
    const two = render(<Layer onBack={() => {}} />)
    two.unmount()
    one.unmount()
    off()
    expect(seen).toEqual([1, 2, 1, 0])
  })

  it('stops telling a subscriber that unsubscribed', () => {
    const fn = vi.fn()
    onLayerDepth(fn)()
    render(<Layer onBack={() => {}} />)
    expect(fn).not.toHaveBeenCalled()
  })

  it('ends at the right depth under StrictMode', () => {
    const { unmount } = render(
      <StrictMode><Layer onBack={() => {}}><Layer onBack={() => {}} /></Layer></StrictMode>)
    expect(layerDepth()).toBe(2)
    unmount()
    expect(layerDepth()).toBe(0)
  })

  it('returns false with nothing open', () => {
    expect(pressBack()).toBe(false)
  })
})

describe('layers: unsaved input', () => {
  it('asks before closing a layer with unsaved input', () => {
    const onBack = vi.fn()
    render(withPrompt(<Layer onBack={onBack} unsaved />))
    expect(pressBack()).toBe(true)
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
    expect(onBack).not.toHaveBeenCalled()
    expect(layerDepth()).toBe(2)
  })

  it('does not ask when nothing is unsaved', () => {
    const onBack = vi.fn()
    render(withPrompt(<Layer onBack={onBack} />))
    pressBack()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('keeps editing on Back at the prompt', () => {
    const onBack = vi.fn()
    render(withPrompt(<Layer onBack={onBack} unsaved />))
    pressBack()
    pressBack()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(onBack).not.toHaveBeenCalled()
    expect(layerDepth()).toBe(1)
  })

  it('closes the layer through its own handler on Discard', () => {
    const onBack = vi.fn()
    render(withPrompt(<Layer onBack={onBack} unsaved />))
    pressBack()
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    expect(onBack).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('focuses Keep editing, and returns focus to the field on it', () => {
    render(withPrompt(<Editor onBack={() => {}} />))
    const field = screen.getByLabelText('title')
    field.focus()
    pressBack()
    // Back left the field first, as a tap elsewhere would.
    expect(field).not.toHaveFocus()
    expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(field).toHaveFocus()
  })

  it('answers Escape at the prompt by keeping editing, and never closes the editor', () => {
    const onClose = vi.fn()
    render(withPrompt(<Editor onBack={() => {}} onClose={onClose} />))
    pressBack()
    fireEvent.keyDown(screen.getByRole('button', { name: 'Keep editing' }), { key: 'Escape' })
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('leaves the field before deciding', () => {
    // A draft that blur moves into the form's state counts as unsaved.
    function Draft({ onBack }: { onBack: () => void }) {
      const [typed, setTyped] = useState('')
      const [draft, setDraft] = useState('')
      useLayer(onBack, { unsaved: draft !== '' })
      return <input aria-label="tag" value={typed}
        onChange={(e) => setTyped(e.target.value)}
        onBlur={() => { setDraft(typed); setTyped('') }} />
    }
    const onBack = vi.fn()
    render(withPrompt(<Draft onBack={onBack} />))
    const field = screen.getByLabelText('tag')
    field.focus()
    fireEvent.change(field, { target: { value: 'home' } })
    pressBack()
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(onBack).not.toHaveBeenCalled()
  })

  it('commits a blur-committed field before the layer closes', () => {
    const calls: string[] = []
    function Setting({ onBack }: { onBack: () => void }) {
      useLayer(onBack)
      return <input aria-label="interval" onBlur={() => calls.push('commit')} />
    }
    render(<Setting onBack={() => calls.push('onBack')} />)
    screen.getByLabelText('interval').focus()
    pressBack()
    expect(calls).toEqual(['commit', 'onBack'])
  })

  it('takes the prompt away with its layer', () => {
    const { rerender } = render(withPrompt(<Layer onBack={() => {}} unsaved />))
    pressBack()
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    rerender(withPrompt(<></>))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(layerDepth()).toBe(0)
  })

  it('drops the question when the layer it asks about stops holding unsaved input', () => {
    const onBack = vi.fn()
    const seen: Array<unknown> = []
    function Probe() {
      seen.push(useDiscardAsk())
      return null
    }
    const { rerender } = render(<>{withPrompt(<Layer onBack={onBack} unsaved />)}<Probe /></>)
    pressBack()
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
    expect(seen[seen.length - 1]).not.toBeNull()

    rerender(<>{withPrompt(<Layer onBack={onBack} unsaved={false} />)}<Probe /></>)
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(seen[seen.length - 1]).toBeNull()
    expect(onBack).not.toHaveBeenCalled()
    expect(layerDepth()).toBe(1)
  })
})

describe('layers: busy', () => {
  it('ignores Back while the top layer waits, without blurring, closing or asking', () => {
    const onBack = vi.fn()
    const ui = (busy: boolean) => withPrompt(
      <Layer onBack={onBack} unsaved busy={busy}><input aria-label="title" /></Layer>)
    const { rerender } = render(ui(true))
    const field = screen.getByLabelText('title')
    field.focus()
    expect(pressBack()).toBe(true)
    expect(onBack).not.toHaveBeenCalled()
    expect(field).toHaveFocus()
    expect(document.activeElement).toBe(field)
    expect(screen.queryByRole('alertdialog')).toBeNull()

    rerender(ui(false))
    expect(pressBack()).toBe(true)
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
    expect(onBack).not.toHaveBeenCalled()
  })
})

// ── focus: a dialog takes it, and gives it back ─────────────────────────────

/** A dialog like the app's: its own element with `tabIndex={-1}`, a close button
 *  and, when asked, a field with `autoFocus`. */
function Dialog({ onClose, name = 'dialog', autoFocusChild = false, unsaved = false, children }: {
  onClose: () => void
  name?: string
  autoFocusChild?: boolean
  unsaved?: boolean
  children?: ReactNode
}) {
  const dialog = useRef<HTMLDivElement>(null)
  useLayer(onClose, { unsaved, dialog })
  return (
    <div ref={dialog} role="dialog" aria-label={name} tabIndex={-1}>
      {autoFocusChild && <input aria-label="field" autoFocus />}
      {children}
      <button onClick={onClose}>close</button>
    </div>
  )
}

/** A trigger button, or a text field that opens on Enter, and the dialog it opens. */
function Opener({ trigger = 'button', beforeClose, ...props }: {
  trigger?: 'button' | 'input'
  beforeClose?: () => void
  autoFocusChild?: boolean
  unsaved?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      {trigger === 'button'
        ? <button onClick={() => setOpen(true)}>open</button>
        : <input aria-label="open" onKeyDown={(e) => { if (e.key === 'Enter') setOpen(true) }} />}
      {open && <Dialog {...props} onClose={() => { beforeClose?.(); setOpen(false) }} />}
    </>
  )
}

/** Open from the trigger the way a user does: focus it, then activate it. */
function openFrom(trigger: HTMLElement) {
  trigger.focus()
  fireEvent.click(trigger)
}

const closeButton = () => screen.getByRole('button', { name: 'close' })

describe('layers: focus', () => {
  it('returns focus to the trigger of a dialog whose child takes autoFocus', () => {
    render(<Opener autoFocusChild />)
    const trigger = screen.getByRole('button', { name: 'open' })
    openFrom(trigger)
    expect(screen.getByLabelText('field')).toHaveFocus()
    fireEvent.click(closeButton())
    // Captured in an effect, the opener would have been the dialog's own field.
    expect(trigger).toHaveFocus()
  })

  it('moves focus into a dialog that takes none, and back on close', () => {
    render(<Opener />)
    const trigger = screen.getByRole('button', { name: 'open' })
    openFrom(trigger)
    expect(screen.getByRole('dialog')).toHaveFocus()
    fireEvent.click(closeButton())
    expect(trigger).toHaveFocus()
  })

  it('gives focus back after Back', () => {
    render(<Opener />)
    const trigger = screen.getByRole('button', { name: 'open' })
    openFrom(trigger)
    pressBack()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(trigger).toHaveFocus()
  })

  it('never gives focus back to a text field', () => {
    render(<Opener trigger="input" />)
    const trigger = screen.getByLabelText('open')
    trigger.focus()
    fireEvent.keyDown(trigger, { key: 'Enter' })
    expect(screen.getByRole('dialog')).toHaveFocus()
    fireEvent.click(closeButton())
    // On a phone, focusing a field opens the keyboard.
    expect(document.activeElement).toBe(document.body)
  })

  it('leaves focus where closing put it', () => {
    render(<>
      <button>other</button>
      <Opener beforeClose={() => screen.getByRole('button', { name: 'other' }).focus()} />
    </>)
    openFrom(screen.getByRole('button', { name: 'open' }))
    fireEvent.click(closeButton())
    expect(screen.getByRole('button', { name: 'other' })).toHaveFocus()
  })

  it('returns focus inside the dialog below when a nested one closes', () => {
    function Stack() {
      const [parent, setParent] = useState(false)
      const [child, setChild] = useState(false)
      return (
        <>
          <button onClick={() => setParent(true)}>open</button>
          {parent && (
            <Dialog onClose={() => setParent(false)}>
              <button onClick={() => setChild(true)}>more</button>
            </Dialog>
          )}
          {child && <Dialog name="child" onClose={() => setChild(false)} />}
        </>
      )
    }
    render(<Stack />)
    openFrom(screen.getByRole('button', { name: 'open' }))
    const more = screen.getByRole('button', { name: 'more' })
    openFrom(more)
    expect(screen.getByRole('dialog', { name: 'child' })).toHaveFocus()
    fireEvent.click(within(screen.getByRole('dialog', { name: 'child' }))
      .getByRole('button', { name: 'close' }))
    expect(screen.queryByRole('dialog', { name: 'child' })).toBeNull()
    expect(more).toHaveFocus()
    expect(screen.getByRole('dialog', { name: 'dialog' })).toBeInTheDocument()
  })

  it('returns focus into the layer below when nothing had focus', () => {
    function Stack() {
      const [child, setChild] = useState(false)
      const dialog = useRef<HTMLDivElement>(null)
      const childRef = useRef<HTMLDivElement>(null)
      useLayer(() => {}, { dialog })
      useLayer(() => setChild(false), { open: child, dialog: childRef })
      return (
        <>
          <div ref={dialog} role="dialog" aria-label="parent" tabIndex={-1}>
            <button onClick={() => setChild(true)}>more</button>
          </div>
          {child && (
            <div ref={childRef} role="dialog" aria-label="child" tabIndex={-1}>
              <button onClick={() => setChild(false)}>close child</button>
            </div>
          )}
        </>
      )
    }
    render(<Stack />)
    const parent = screen.getByRole('dialog', { name: 'parent' })
    screen.getByRole('button', { name: 'more' }).focus()
    ;(document.activeElement as HTMLElement).blur()
    // Opened with nothing focused, as a script or an assistive click does.
    fireEvent.click(screen.getByRole('button', { name: 'more' }))
    expect(screen.getByRole('dialog', { name: 'child' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'close child' }))
    expect(parent).toHaveFocus()
  })

  it('follows the chain when the opening layer closed as this one opened', () => {
    function Handover() {
      const [which, setWhich] = useState<'a' | 'b' | null>(null)
      return (
        <>
          <button onClick={() => setWhich('a')}>open</button>
          {which === 'a' && (
            <Dialog onClose={() => setWhich(null)}>
              <button onClick={() => setWhich('b')}>hand over</button>
            </Dialog>
          )}
          {which === 'b' && <Dialog autoFocusChild onClose={() => setWhich(null)} />}
        </>
      )
    }
    render(<Handover />)
    const trigger = screen.getByRole('button', { name: 'open' })
    openFrom(trigger)
    fireEvent.click(screen.getByRole('button', { name: 'hand over' }))
    expect(screen.getByLabelText('field')).toHaveFocus()
    fireEvent.click(closeButton())
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(trigger).toHaveFocus()
  })

  it('a flag-opened layer gives focus back, and takes it again on reopening', () => {
    function Flag() {
      const [open, setOpen] = useState(false)
      const dialog = useRef<HTMLDivElement>(null)
      useLayer(() => setOpen(false), { open, dialog })
      return (
        <>
          <button onClick={() => setOpen(true)}>open</button>
          {open && (
            <div ref={dialog} role="dialog" aria-label="dialog" tabIndex={-1}>
              <button onClick={() => setOpen(false)}>close</button>
            </div>
          )}
        </>
      )
    }
    render(<Flag />)
    const trigger = screen.getByRole('button', { name: 'open' })
    openFrom(trigger)
    expect(screen.getByRole('dialog')).toHaveFocus()
    fireEvent.click(closeButton())
    expect(trigger).toHaveFocus()
    openFrom(trigger)
    expect(screen.getByRole('dialog')).toHaveFocus()
    fireEvent.click(closeButton())
    expect(trigger).toHaveFocus()
  })

  it("Discard returns focus to the editor's trigger", () => {
    render(withPrompt(<Opener unsaved autoFocusChild />))
    const trigger = screen.getByRole('button', { name: 'open' })
    openFrom(trigger)
    pressBack()
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(trigger).toHaveFocus()
  })

  it('keeps autoFocus, and returns focus, under StrictMode', () => {
    const { unmount } = render(<StrictMode><Opener autoFocusChild /></StrictMode>)
    const trigger = screen.getByRole('button', { name: 'open' })
    openFrom(trigger)
    expect(screen.getByLabelText('field')).toHaveFocus()
    fireEvent.click(closeButton())
    expect(trigger).toHaveFocus()
    unmount()

    render(<StrictMode><Opener /></StrictMode>)
    const plain = screen.getByRole('button', { name: 'open' })
    openFrom(plain)
    expect(screen.getByRole('dialog')).toHaveFocus()
    fireEvent.click(closeButton())
    expect(plain).toHaveFocus()
  })
})

describe('unsent input in fields the layer cannot see', () => {
  function Field({ label, initial = '' }: { label: string; initial?: string }) {
    const [text, setText] = useState(initial)
    useUnsent(text !== '')
    return <input aria-label={label} value={text} onChange={(e) => setText(e.target.value)} />
  }
  function Sheet({ onBack, children }: { onBack: () => void; children: ReactNode }) {
    const [unsent, report] = useUnsentCount()
    useLayer(onBack, { unsaved: unsent > 0 })
    return <UnsentInput.Provider value={report}>{children}</UnsentInput.Provider>
  }

  it('asks while any field holds text, and stops once all are empty, in StrictMode too', () => {
    // StrictMode runs each effect, its cleanup, and the effect again, so a
    // count that only ever went up would stay unsaved forever.
    const onBack = vi.fn()
    render(withPrompt(
      <StrictMode>
        <Sheet onBack={onBack}><Field label="a" /><Field label="b" /></Sheet>
      </StrictMode>,
    ))
    const a = screen.getByLabelText('a')
    const b = screen.getByLabelText('b')
    fireEvent.change(a, { target: { value: 'x' } })
    fireEvent.change(b, { target: { value: 'y' } })
    fireEvent.change(a, { target: { value: '' } })

    pressBack()
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(onBack).not.toHaveBeenCalled()

    fireEvent.change(b, { target: { value: '' } })
    pressBack()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(onBack).toHaveBeenCalledOnce()
  })

  it('counts a field once though StrictMode mounts it twice', () => {
    // StrictMode runs the effect, its cleanup and the effect again while the
    // field already holds text. A release that did not undo its report would
    // leave the count at 2, and clearing the field would still ask.
    const onBack = vi.fn()
    render(withPrompt(
      <StrictMode>
        <Sheet onBack={onBack}><Field label="a" initial="x" /></Sheet>
      </StrictMode>,
    ))
    pressBack()
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }))

    fireEvent.change(screen.getByLabelText('a'), { target: { value: '' } })
    pressBack()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(onBack).toHaveBeenCalledOnce()
  })

  it('is inert outside a layer that provides it', () => {
    render(<Field label="loose" />)
    fireEvent.change(screen.getByLabelText('loose'), { target: { value: 'x' } })
    expect(layerDepth()).toBe(0)
  })
})

describe('pending writes in sections the layer cannot see', () => {
  function Section({ label, pending }: { label: string; pending: boolean }) {
    usePending(pending)
    return <span>{label}</span>
  }
  function Sheet({ onBack, children }: { onBack: () => void; children: ReactNode }) {
    const [pending, report] = usePendingCount()
    useLayer(onBack, { busy: pending > 0 })
    return <PendingWrite.Provider value={report}>
      <output aria-label="pending">{pending}</output>{children}
    </PendingWrite.Provider>
  }
  const count = () => screen.getByLabelText('pending').textContent

  it('counts a section while it reports pending, and not once it stops or unmounts', () => {
    const onBack = vi.fn()
    const ui = (a: boolean, b: boolean | null) => (
      <Sheet onBack={onBack}>
        <Section label="a" pending={a} />
        {b !== null && <Section label="b" pending={b} />}
      </Sheet>
    )
    const { rerender } = render(ui(false, false))
    expect(count()).toBe('0')
    rerender(ui(true, false))
    expect(count()).toBe('1')
    rerender(ui(true, true))
    expect(count()).toBe('2')
    expect(pressBack()).toBe(true)
    expect(onBack).not.toHaveBeenCalled()
    rerender(ui(false, true))
    expect(count()).toBe('1')
    rerender(ui(false, null))
    expect(count()).toBe('0')
    pressBack()
    expect(onBack).toHaveBeenCalledOnce()
  })

  it('counts a section once under StrictMode, and releases it', () => {
    const onBack = vi.fn()
    const ui = (pending: boolean) => (
      <StrictMode><Sheet onBack={onBack}><Section label="a" pending={pending} /></Sheet></StrictMode>
    )
    const { rerender } = render(ui(true))
    expect(count()).toBe('1')
    rerender(ui(false))
    expect(count()).toBe('0')
    pressBack()
    expect(onBack).toHaveBeenCalledOnce()
  })

  it('is inert outside a layer that provides it', () => {
    render(<Section label="loose" pending />)
    expect(layerDepth()).toBe(0)
    expect(screen.getByText('loose')).toBeInTheDocument()
  })
})

describe('DiscardPrompt: Tab', () => {
  it('keeps Tab and Shift+Tab on the two answers', async () => {
    const user = userEvent.setup()
    render(withPrompt(<>
      <button>before</button>
      <Layer onBack={() => {}} unsaved><input aria-label="title" /></Layer>
      <button>after</button>
    </>))
    pressBack()
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toContainElement(document.activeElement as HTMLElement)
    const presses = [false, false, false, true, true, false, true, true, false, false, true]
    for (const shift of presses) {
      await user.tab({ shift })
      expect(dialog).toContainElement(document.activeElement as HTMLElement)
    }

    // From Keep editing, Tab comes round to Discard, and Shift+Tab from Discard to Keep editing.
    screen.getByRole('button', { name: 'Keep editing' }).focus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Discard' })).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus()

    dialog.focus()
    expect(dialog).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus()
  })
})

describe('DiscardPrompt: the shield', () => {
  const shield = () => document.querySelector('.discard-shield')

  // Fake timers, so that a slow machine cannot run the 400 ms out between the
  // answer and the assertions.
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  function answered(button: string) {
    render(withPrompt(<Layer onBack={() => {}} unsaved />))
    expect(shield()).toBeNull()
    pressBack()
    expect(shield()).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: button }))
  }

  it('covers the page after Keep editing, takes presses, and goes after SHIELD_MS', () => {
    answered('Keep editing')
    const el = shield() as HTMLElement
    expect(el).not.toBeNull()
    expect(el).toHaveAttribute('aria-hidden', 'true')

    const seen = vi.fn()
    const clicked = vi.fn()
    document.addEventListener('mousedown', seen)
    document.addEventListener('click', clicked)
    try {
      const event = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
      el.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(true)
      expect(fireEvent.mouseDown(el)).toBe(false)
      expect(seen).not.toHaveBeenCalled()
      fireEvent.click(el)
      expect(clicked).not.toHaveBeenCalled()
    } finally {
      document.removeEventListener('mousedown', seen)
      document.removeEventListener('click', clicked)
    }

    act(() => { vi.advanceTimersByTime(SHIELD_MS - 1) })
    expect(shield()).not.toBeNull()
    act(() => { vi.advanceTimersByTime(1) })
    expect(shield()).toBeNull()
  })

  it('stands after Discard too', () => {
    answered('Discard')
    const el = shield() as HTMLElement
    expect(el).not.toBeNull()
    expect(el).toHaveAttribute('aria-hidden', 'true')
    act(() => { vi.advanceTimersByTime(SHIELD_MS) })
    expect(shield()).toBeNull()
  })
})
