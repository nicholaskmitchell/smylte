import { afterEach, describe, expect, it, vi } from 'vitest'
import { StrictMode, useState, type ReactNode } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useEscape } from './hooks'
import { backTopLayer, layerDepth, onLayerDepth, useLayer } from './layers'
import { pressBack, withPrompt } from './test/back'

afterEach(cleanup)

function Layer({ onBack, name, ...options }: {
  onBack: () => void
  name?: string
  open?: boolean
  unsaved?: boolean
  children?: ReactNode
}) {
  useLayer(onBack, { open: options.open, unsaved: options.unsaved })
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
})
