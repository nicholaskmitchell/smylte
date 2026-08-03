import { useEffect, useMemo, useRef, useState } from 'react'
import { clientId } from '../api'
import {
  DEFAULTS, FONT_CHOICES, GROUPS, MAX_NAME_LEN, MAX_THEMES, SHARED_DEFAULTS, TOKENS,
  defaultValue, ensureFont, isValidToken, parseTheme, serializeTheme, toSwatchHex,
  type Appearance, type CustomTheme, type Mode, type ThemeTokens, type TokenSpec,
} from '../appearance'

// The live editor for the appearance override layer.
//
// There is no separate preview pane: edits apply to the document as you make
// them, so the app behind the modal *is* the preview. That is only safe because
// every write goes through the same validation the loader uses — an invalid
// value is refused at the input, never half-applied.
//
// Editing always targets a custom theme. Touching a control while the shipped
// default is active forks it into a new theme first (`Custom`), so "Smylte" can
// never be edited out from under the user — reverting is always one click.

export function AppearancePanel({ appearance, onChange, mode, onMode, onClose }: {
  appearance: Appearance
  onChange: (next: Appearance) => void
  mode: Mode
  onMode: (next: Mode) => void
  onClose: () => void
}) {
  const themes = appearance.themes ?? []
  const active = themes.find((t) => t.id === appearance.active) ?? null
  const fileRef = useRef<HTMLInputElement>(null)
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState('')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  /** Write `tokens` into the active theme for the current mode, forking first. */
  const edit = (patch: ThemeTokens) => {
    if (active) {
      const next = { ...active, [mode]: { ...active[mode], ...patch } }
      onChange({ active: active.id, themes: themes.map((t) => (t.id === active.id ? next : t)) })
      return
    }
    if (themes.length >= MAX_THEMES) return
    const fork: CustomTheme = {
      id: clientId().slice(0, 16),
      name: 'Custom',
      base: mode,
      light: {},
      dark: {},
      [mode]: patch,
    }
    onChange({ active: fork.id, themes: [...themes, fork] })
  }

  const selectTheme = (id: string) => onChange({ ...appearance, active: id || null })

  const saveAs = () => {
    if (!active || themes.length >= MAX_THEMES) return
    const copy: CustomTheme = {
      ...active, id: clientId().slice(0, 16), name: `${active.name} copy`.slice(0, MAX_NAME_LEN),
    }
    onChange({ active: copy.id, themes: [...themes, copy] })
  }

  const rename = (to: string) => {
    if (!active) return
    const clean = to.trim().slice(0, MAX_NAME_LEN)
    if (!clean) return
    onChange({
      active: active.id,
      themes: themes.map((t) => (t.id === active.id ? { ...t, name: clean } : t)),
    })
  }

  const remove = () => {
    if (!active) return
    onChange({ active: null, themes: themes.filter((t) => t.id !== active.id) })
  }

  /** Drop every override for this mode — back to the shipped values. */
  const resetMode = () => {
    if (!active) return
    onChange({
      active: active.id,
      themes: themes.map((t) => (t.id === active.id ? { ...t, [mode]: {} } : t)),
    })
  }

  const exportTheme = () => {
    if (!active) return
    const blob = new Blob([serializeTheme(active)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${active.name.replace(/[^\w-]+/g, '-').toLowerCase()}.smylte-theme.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const importTheme = async (file: File) => {
    const parsed = parseTheme(await file.text(), clientId().slice(0, 16))
    if (!parsed) { window.alert('That file is not a Smylte theme.'); return }
    if (themes.length >= MAX_THEMES) { window.alert(`You can keep ${MAX_THEMES} themes.`); return }
    onChange({ active: parsed.id, themes: [...themes, parsed] })
  }

  // What each control shows: the override if there is one, else the shipped value.
  const current = useMemo(() => {
    const overrides = active?.[mode] ?? {}
    const out: ThemeTokens = {}
    for (const token of Object.keys(TOKENS)) {
      out[token] = overrides[token] ?? defaultValue(token, mode)
    }
    return out
  }, [active, mode])

  const overridden = active?.[mode] ?? {}

  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal appearance-modal" role="dialog" aria-label="Appearance" aria-modal="true">
        <div className="modal-head">
          <span className="modal-title">Appearance</span>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>

        {/* ---- theme ---- */}
        <div className="appear-bar">
          <select className="input" value={active?.id ?? ''} aria-label="Theme"
            onChange={(e) => selectTheme(e.target.value)}>
            <option value="">Smylte (default)</option>
            {themes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <button className="btn ghost" onClick={saveAs} disabled={!active}>Duplicate</button>
          <button className="btn ghost" onClick={() => { setName(active?.name ?? ''); setRenaming(true) }}
            disabled={!active}>Rename</button>
          <button className="btn ghost" onClick={exportTheme} disabled={!active}>Export</button>
          <button className="btn ghost" onClick={() => fileRef.current?.click()}>Import</button>
          <input ref={fileRef} type="file" accept="application/json,.json" hidden
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) importTheme(f)
              e.target.value = ''
            }} />
        </div>

        {renaming && active && (
          <div className="appear-bar">
            <input className="input" value={name} autoFocus maxLength={MAX_NAME_LEN}
              aria-label="Theme name" onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { rename(name); setRenaming(false) } }} />
            <button className="btn" onClick={() => { rename(name); setRenaming(false) }}>Save</button>
            <button className="btn ghost" onClick={() => setRenaming(false)}>Cancel</button>
          </div>
        )}

        <p className="hintline">
          {active
            ? 'Editing this theme. Smylte’s own design is never modified — switch back to it any time.'
            : 'Smylte’s shipped design. Change anything below and it forks into a theme of your own.'}
        </p>

        {/* ---- which mode am I editing ---- */}
        <div className="appear-modes" role="group" aria-label="Editing mode">
          {(['light', 'dark'] as Mode[]).map((m) => (
            <button key={m} className={`view-tab ${mode === m ? 'active' : ''}`}
              aria-pressed={mode === m} onClick={() => onMode(m)}>
              {m === 'light' ? 'Light' : 'Dark'}
            </button>
          ))}
          <span className="spacer" />
          <span className="hintline">
            {Object.keys(overridden).length} override{Object.keys(overridden).length === 1 ? '' : 's'} in {mode}
          </span>
        </div>

        {/* ---- the tokens ---- */}
        <div className="appear-groups">
          {GROUPS.map((group) => {
            const entries = Object.entries(TOKENS).filter(([, s]) => s.group === group)
            if (!entries.length) return null
            return (
              <section key={group} className="appear-group">
                <div className="menu-head">{group}</div>
                {entries.map(([token, spec]) => (
                  <TokenRow key={token} token={token} spec={spec}
                    value={current[token]} isOverride={token in overridden}
                    onChange={(v) => edit({ [token]: v })}
                    onClear={() => {
                      if (!active) return
                      const next = { ...overridden }
                      delete next[token]
                      onChange({
                        active: active.id,
                        themes: themes.map((t) => (t.id === active.id ? { ...t, [mode]: next } : t)),
                      })
                    }} />
                ))}
              </section>
            )
          })}
        </div>

        <div className="modal-actions">
          {active && <button className="btn ghost" onClick={resetMode}>Reset {mode}</button>}
          {active && <button className="btn ghost danger" onClick={remove}>Delete theme</button>}
          <button className="btn" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  )
}

// ── one token, one row ──────────────────────────────────────────────────────

function TokenRow({ token, spec, value, isOverride, onChange, onClear }: {
  token: string
  spec: TokenSpec
  value: string
  isOverride: boolean
  onChange: (value: string) => void
  onClear: () => void
}) {
  return (
    <div className="appear-row">
      <label className="appear-label" htmlFor={`tok${token}`}>
        {spec.label}
        {spec.hint && <span className="appear-hint">{spec.hint}</span>}
      </label>
      <div className="appear-control">
        {spec.kind === 'color' && <ColorControl id={token} value={value} onChange={onChange} />}
        {spec.kind === 'font' && <FontControl id={token} token={token} value={value} onChange={onChange} />}
        {(spec.kind === 'length' || spec.kind === 'scale') &&
          <RangeControl id={token} token={token} spec={spec} value={value} onChange={onChange} />}
        <button className="appear-clear" onClick={onClear} disabled={!isOverride}
          title="Back to the Smylte value" aria-label={`Reset ${spec.label}`}>↺</button>
      </div>
    </div>
  )
}

function ColorControl({ id, value, onChange }: {
  id: string; value: string; onChange: (v: string) => void
}) {
  // Two inputs on purpose. The native picker is the fast path but is sRGB-hex
  // only, and this design system is authored in OKLCH — so the text field
  // accepts the real value and is what a theme round-trips through. Typing is
  // debounced into local state so a half-typed `oklch(0.6` is not applied.
  const [text, setText] = useState(value)
  useEffect(() => { setText(value) }, [value])
  const valid = isValidToken(id, text)
  const swatch = toSwatchHex(value)

  return (
    <>
      <input type="color" className="appear-swatch" value={swatch}
        aria-label="Pick a color" onChange={(e) => onChange(e.target.value)} />
      <input id={`tok${id}`} className={`input mono appear-text ${valid ? '' : 'bad'}`}
        value={text} spellCheck={false}
        onChange={(e) => {
          setText(e.target.value)
          if (isValidToken(id, e.target.value)) onChange(e.target.value.trim())
        }} />
    </>
  )
}

function FontControl({ id, token, value, onChange }: {
  id: string; token: string; value: string; onChange: (v: string) => void
}) {
  const tier = token === '--serif' ? 'serif' : token === '--sans' ? 'sans' : 'mono'
  const choices = FONT_CHOICES[tier]
  // A theme imported with a stack we don't offer still needs a stable option to
  // sit on, rather than silently snapping to the default.
  const known = choices.some((c) => c.stack === value)
  return (
    <select id={`tok${id}`} className="input" value={known ? value : ''}
      onChange={(e) => { ensureFont(e.target.value); onChange(e.target.value) }}>
      {!known && <option value="">Custom ({value.split(',')[0].replace(/"/g, '')})</option>}
      {choices.map((c) => <option key={c.label} value={c.stack}>{c.label}</option>)}
    </select>
  )
}

function RangeControl({ id, token, spec, value, onChange }: {
  id: string; token: string; spec: TokenSpec; value: string; onChange: (v: string) => void
}) {
  const unit = spec.kind === 'length' ? 'px' : ''
  const step = spec.kind === 'scale' ? 0.05 : 1
  const n = parseFloat(value)
  const shipped = parseFloat(SHARED_DEFAULTS[token] ?? DEFAULTS.light[token] ?? '0')
  return (
    <>
      <input id={`tok${id}`} type="range" className="appear-range"
        min={spec.min ?? 0} max={spec.max ?? 100} step={step}
        value={Number.isNaN(n) ? shipped : n}
        onChange={(e) => onChange(`${e.target.value}${unit}`)} />
      <span className="appear-num mono">{Number.isNaN(n) ? shipped : n}{unit}</span>
    </>
  )
}
