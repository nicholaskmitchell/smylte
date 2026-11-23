import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { HomeInk, IconInk, type Icon } from './Marks'

// The pen's icon set. Geometry only: size, stroke and colour are CSS
// (fieldnotes.css), and icons.browser.test.tsx measures those.
const ALL: Icon[] = ['left', 'right', 'close', 'plus', 'up', 'down', 'foldLeft', 'foldRight',
  'check', 'pause', 'more', 'caret', 'date', 'time']

describe('<IconInk>', () => {
  it.each(ALL)('draws %s on the 24-unit grid, hidden from assistive tech', (icon) => {
    const { container } = render(<IconInk icon={icon} />)
    const svg = container.querySelector('svg')!
    expect(svg).toHaveClass('icon-ink')
    expect(svg).toHaveAttribute('data-icon', icon)
    expect(svg).toHaveAttribute('viewBox', '0 0 24 24')
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg).toHaveAttribute('focusable', 'false')
    const paths = [...svg.querySelectorAll('path')]
    expect(paths.length).toBeGreaterThan(0)
    for (const p of paths) expect(p.getAttribute('d')).toMatch(/^M\d/)
  })

  it('names no size, stroke or colour of its own: the pen is CSS', () => {
    const { container } = render(<>{ALL.map((i) => <IconInk key={i} icon={i} />)}</>)
    for (const el of container.querySelectorAll('svg, path')) {
      for (const a of ['width', 'height', 'stroke', 'stroke-width', 'fill', 'style']) {
        expect(el.hasAttribute(a), `${el.tagName} has ${a}`).toBe(false)
      }
    }
  })

  it('adds a class for a place that sizes it on its own', () => {
    const { container } = render(<IconInk icon="right" className="share-list__chev" />)
    expect(container.querySelector('svg')!.getAttribute('class')).toBe('icon-ink share-list__chev')
  })
})

describe('<HomeInk>', () => {
  it('is an aria-hidden arrow, wider than tall', () => {
    const { container } = render(<HomeInk />)
    const svg = container.querySelector('svg')!
    expect(svg).toHaveClass('day-home-ink')
    expect(svg).toHaveAttribute('viewBox', '0 0 21 14')
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg.querySelectorAll('path')).toHaveLength(2)
  })
})
