import { describe, expect, it, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Hint } from './Hint'

afterEach(() => {
  document.documentElement.removeAttribute('data-surface')
})

describe('<Hint>', () => {
  it('renders its children under a preset', () => {
    render(<Hint id="h">Syncs to your other apps</Hint>)
    const line = screen.getByText('Syncs to your other apps')
    expect(line.tagName).toBe('DIV')
    expect(line).toHaveClass('hintline')
    expect(line).toHaveAttribute('id', 'h')
  })

  it('takes the element and the class it is given', () => {
    render(<Hint as="p" className="plan-hint">Note</Hint>)
    const line = screen.getByText('Note')
    expect(line.tagName).toBe('P')
    expect(line).toHaveClass('plan-hint')
    expect(line).not.toHaveClass('hintline')
  })

  it('renders nothing under Field notes', () => {
    document.documentElement.setAttribute('data-surface', 'app')
    const { container } = render(<Hint>Syncs to your other apps</Hint>)
    expect(screen.queryByText('Syncs to your other apps')).not.toBeInTheDocument()
    expect(container).toBeEmptyDOMElement()
  })
})
