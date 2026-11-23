import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { InkSelect } from './InkSelect'

describe('<InkSelect>', () => {
  it('is the select it wraps, with the pen\'s caret beside it', () => {
    const onChange = vi.fn()
    const { container } = render(
      <InkSelect id="lang" className="menu-toggle" aria-label="Language" value="en" onChange={onChange}>
        <option value="en">English</option><option value="de">Deutsch</option>
      </InkSelect>)
    const select = screen.getByRole('combobox', { name: 'Language' })
    expect(select).toHaveAttribute('id', 'lang')
    expect(select).toHaveClass('menu-toggle')
    expect(select.parentElement).toHaveClass('ink-field')
    expect(container.querySelector('.ink-field > select + svg.icon-ink[data-icon="caret"][aria-hidden="true"]'))
      .not.toBeNull()
    fireEvent.change(select, { target: { value: 'de' } })
    expect(onChange).toHaveBeenCalledTimes(1)
  })
})
