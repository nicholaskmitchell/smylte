import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppearancePanel } from './AppearancePanel'
import { DEFAULTS, type Appearance, type CustomTheme } from '../appearance'

const theme = (o: Partial<CustomTheme> = {}): CustomTheme => ({
  id: 't1', name: 'Mine', base: 'light',
  light: { '--accent': '#ff0000' }, dark: {}, ...o,
})

function setup(appearance: Appearance = {}, mode: 'light' | 'dark' = 'light') {
  const onChange = vi.fn()
  const onMode = vi.fn()
  render(<AppearancePanel appearance={appearance} onChange={onChange}
    mode={mode} onMode={onMode} onClose={vi.fn()} />)
  return { onChange, onMode }
}

// The accent row's raw-value text box — the control most tests drive. Selected
// by label rather than value: the row also carries a native color swatch, which
// mirrors the same value.
const accentField = () => screen.getByLabelText('Accent') as HTMLInputElement

beforeEach(() => vi.clearAllMocks())

describe('<AppearancePanel> protecting the default', () => {
  it('opens on the shipped design with nothing overridden', () => {
    setup()
    expect(screen.getByRole('combobox', { name: 'Theme' })).toHaveValue('')
    expect(screen.getByText(/forks into a theme of your own/i)).toBeInTheDocument()
  })

  it('shows the shipped values as the starting point', () => {
    setup()
    expect(accentField()).toHaveValue(DEFAULTS.light['--accent'])
  })

  it('forks into a new theme rather than editing Smylte', async () => {
    // The load-bearing behaviour: the shipped design is never mutated, so
    // switching back to it always restores the original look.
    const { onChange } = setup()
    const field = accentField()
    await userEvent.clear(field)
    await userEvent.type(field, '#00ff00')

    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0] as Appearance
    expect(last.themes).toHaveLength(1)
    expect(last.active).toBe(last.themes![0].id)
    expect(last.themes![0].light['--accent']).toBe('#00ff00')
  })

  it('writes into the existing theme once one is active', async () => {
    const { onChange } = setup({ active: 't1', themes: [theme()] })
    const field = accentField()
    await userEvent.clear(field)
    await userEvent.type(field, '#0000ff')

    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0] as Appearance
    expect(last.themes).toHaveLength(1)          // no second fork
    expect(last.themes![0].id).toBe('t1')
  })

  it('never emits a value that failed validation', async () => {
    const { onChange } = setup({ active: 't1', themes: [theme()] })
    const field = accentField()
    await userEvent.clear(field)
    await userEvent.type(field, 'url(//evil)')

    for (const [next] of onChange.mock.calls) {
      const value = (next as Appearance).themes?.[0]?.light['--accent']
      expect(value ?? '').not.toContain('url(')
    }
  })

  it('returns to the shipped design by selecting it', async () => {
    const { onChange } = setup({ active: 't1', themes: [theme()] })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Theme' }), '')
    expect(onChange).toHaveBeenCalledWith({ active: null, themes: [theme()] })
  })
})

describe('<AppearancePanel> theme management', () => {
  it('reports how much of the current mode is overridden', () => {
    setup({ active: 't1', themes: [theme({ light: { '--accent': '#ff0000', '--radius': '4px' } })] })
    expect(screen.getByText('2 overrides in light')).toBeInTheDocument()
  })

  it('counts each mode separately, since a theme carries both', () => {
    setup({ active: 't1', themes: [theme()] }, 'dark')
    expect(screen.getByText('0 overrides in dark')).toBeInTheDocument()
  })

  it('clears just this mode on reset, leaving the other alone', async () => {
    const t = theme({ light: { '--accent': '#ff0000' }, dark: { '--accent': '#00ff00' } })
    const { onChange } = setup({ active: 't1', themes: [t] })
    await userEvent.click(screen.getByRole('button', { name: /reset light/i }))

    const next = onChange.mock.calls[0][0] as Appearance
    expect(next.themes![0].light).toEqual({})
    expect(next.themes![0].dark).toEqual({ '--accent': '#00ff00' })
  })

  it('deletes a theme back to the shipped default', async () => {
    const { onChange } = setup({ active: 't1', themes: [theme()] })
    await userEvent.click(screen.getByRole('button', { name: /delete theme/i }))
    expect(onChange).toHaveBeenCalledWith({ active: null, themes: [] })
  })

  it('duplicates the active theme under a new id', async () => {
    const { onChange } = setup({ active: 't1', themes: [theme()] })
    await userEvent.click(screen.getByRole('button', { name: 'Duplicate' }))

    const next = onChange.mock.calls[0][0] as Appearance
    expect(next.themes).toHaveLength(2)
    expect(next.themes![1].id).not.toBe('t1')
    expect(next.themes![1].light).toEqual({ '--accent': '#ff0000' })
    expect(next.active).toBe(next.themes![1].id)
  })

  it('resets one token without touching the rest', async () => {
    const t = theme({ light: { '--accent': '#ff0000', '--radius': '4px' } })
    const { onChange } = setup({ active: 't1', themes: [t] })
    await userEvent.click(screen.getByRole('button', { name: /reset accent/i }))

    const next = onChange.mock.calls[0][0] as Appearance
    expect(next.themes![0].light).toEqual({ '--radius': '4px' })
  })

  it('disables the per-token reset for a token that is not overridden', () => {
    setup({ active: 't1', themes: [theme({ light: {} })] })
    expect(screen.getByRole('button', { name: /reset accent/i })).toBeDisabled()
  })

  it('offers no theme-scoped action while the shipped design is active', () => {
    setup()
    expect(screen.getByRole('button', { name: 'Duplicate' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Export' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /delete theme/i })).not.toBeInTheDocument()
  })

  it('switches which mode is being edited', async () => {
    const { onMode } = setup({ active: 't1', themes: [theme()] })
    await userEvent.click(screen.getByRole('button', { name: 'Dark' }))
    expect(onMode).toHaveBeenCalledWith('dark')
  })
})
