import { useEffect, useMemo, useRef, useState } from 'react'
import { clientId } from '../api'
import { useEscape } from '../hooks'
import { useT } from '../i18n'
import {
  DEFAULTS, FONT_CHOICES, GROUPS, MAX_NAME_LEN, MAX_THEMES, PRESETS, SHARED_DEFAULTS,
  GROUP_LABEL, TOKENS, defaultValue, ensureFont, findPreset, isSharedToken, isValidToken,
  parseTheme, serializeTheme, themeTokens, toSwatchHex,
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
//
// A built-in preset is as un-editable as Smylte itself and for the same reason:
// it is shipped design, not the user's data. It differs only in what a fork
// seeds from — a copy of Smylte starts empty, because empty *is* Smylte, while a
// copy of a preset has to carry that preset's values or it would snap back to
// the default look the moment a slider moved.

// Every path that would need to create a theme says the same thing when there
// is no room for one, rather than each failing its own silent way. A KEY now,
// resolved at the two call sites — a module constant has no translator.
const AT_CAP = 'appear.atCap'

export function AppearancePanel({ appearance, onChange, mode, onMode, onClose }: {
  appearance: Appearance
  onChange: (next: Appearance) => void
  mode: Mode
  onMode: (next: Mode) => void
  onClose: () => void
}) {
  const tr = useT()
  // The mode as a WORD, twice on this screen: inside a sentence ("2 overrides
  // in dark") and on a button ("Reset dark"). Both want the lowercase form —
  // German capitalises nouns, not adjectives — while the two tabs above want
  // the capitalised one, which is why there are two keys and not a `.toLower`.
  const modeWord = mode === 'light' ? 'appear.lightLower' : 'appear.darkLower'
  const themes = appearance.themes ?? []
  // A preset's id *is* `appearance.active`, so everything downstream that reads
  // `active` — the picker's value, `current`, export — works unchanged.
  const preset = findPreset(appearance.active)
  const active = preset ?? themes.find((t) => t.id === appearance.active) ?? null
  const isPreset = !!preset
  const fileRef = useRef<HTMLInputElement>(null)
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState('')

  // Was bound to `document`, which does not see a keydown dispatched at
  // `window` — one of the three bindings this hook exists to collapse.
  useEscape(onClose)

  // Close the rename row whenever the theme it was opened for stops being the
  // active one. `renaming`/`name` are captured when Rename is pressed and were
  // cleared only by the row's own Save and Cancel, while the row's guard is
  // `renaming && active` — "some theme is active", not "still the one this was
  // about". The picker sits directly above it, so switching themes left the row
  // open, pre-filled with the previous theme's name and bound to a different
  // object: Save then renamed the NEW theme to the OLD one's name, and since ids
  // are never shown, the name is the only thing that tells two themes apart.
  //
  // One effect covers all three paths that retarget `active` — the picker,
  // Duplicate and Import — because all three write it. Closing rather than
  // re-priming: re-priming would silently change what the row is about while the
  // user is looking at it, which is a second version of the same defect.
  useEffect(() => { setRenaming(false) }, [appearance.active])

  /**
   * A new theme carrying everything `source` has, or an empty one when there is
   * no source — which is how a copy of Smylte stays lossless.
   */
  const seedFork = (source: CustomTheme | null): CustomTheme => ({
    id: clientId().slice(0, 16),
    name: (source
      ? tr('appear.copySuffix', { name: source.name })
      : tr('appear.custom')).slice(0, MAX_NAME_LEN),
    base: source?.base ?? mode,
    light: { ...(source?.light ?? {}) },
    dark: { ...(source?.dark ?? {}) },
  })

  /**
   * A patch, split by whether each token varies with the mode.
   *
   * The nine in SHARED_DEFAULTS are declared once in tokens.css's `:root` block
   * and have no dark counterpart, so writing a corner radius or a typeface into
   * `active[mode]` alone meant it disappeared the moment the app flipped — with
   * the theme still selected and named, and no way in the panel to author these
   * once for both. They go into BOTH maps; colours keep going into the current
   * mode only, or a dark theme would be repainted in its light values.
   */
  const splitPatch = (t: CustomTheme, patch: ThemeTokens): CustomTheme => {
    const own: ThemeTokens = {}
    const shared: ThemeTokens = {}
    for (const [token, value] of Object.entries(patch)) {
      if (isSharedToken(token)) shared[token] = value
      else own[token] = value
    }
    const other: Mode = mode === 'dark' ? 'light' : 'dark'
    return {
      ...t,
      [mode]: { ...t[mode], ...shared, ...own },
      [other]: { ...t[other], ...shared },
    }
  }

  /** Write `tokens` into the active theme for the current mode, forking first. */
  const edit = (patch: ThemeTokens) => {
    if (active && !isPreset) {
      const next = splitPatch(active, patch)
      onChange({ active: active.id, themes: themes.map((t) => (t.id === active.id ? next : t)) })
      return
    }
    // Editing a shipped design — the default or a preset — forks a new theme, so
    // with no room for one there is nothing to write. This used to be a bare
    // `return`: the panel stayed fully interactive, the sliders moved and the
    // color field accepted typing, and nothing was ever applied or saved.
    if (themes.length >= MAX_THEMES) { window.alert(tr(AT_CAP, { max: MAX_THEMES })); return }
    // Merged, not replaced: the seed has to survive the very edit that made it.
    const fork = splitPatch(seedFork(preset), patch)
    onChange({ active: fork.id, themes: [...themes, fork] })
  }

  const selectTheme = (id: string) => onChange({ ...appearance, active: id || null })

  const saveAs = () => {
    if (!active) return
    if (themes.length >= MAX_THEMES) { window.alert(tr(AT_CAP, { max: MAX_THEMES })); return }
    const copy = seedFork(active)
    onChange({ active: copy.id, themes: [...themes, copy] })
  }

  const rename = (to: string) => {
    if (!active || isPreset) return
    const clean = to.trim().slice(0, MAX_NAME_LEN)
    if (!clean) return
    onChange({
      active: active.id,
      themes: themes.map((t) => (t.id === active.id ? { ...t, name: clean } : t)),
    })
  }

  const remove = () => {
    if (!active || isPreset) return
    onChange({ active: null, themes: themes.filter((t) => t.id !== active.id) })
  }

  /** Drop every override for this mode — back to the shipped values.
   *
   *  The shared tokens go from the other map too. They count for both modes now
   *  (see `themeTokens`) and the override counter counts them in both, so
   *  leaving them behind would make this button visibly do nothing: the count
   *  would still read above zero straight after a reset, and the corner radius
   *  would go on resolving from the map the user did not reset. */
  const resetMode = () => {
    if (!active || isPreset) return
    const other: Mode = mode === 'dark' ? 'light' : 'dark'
    const keptOther = Object.fromEntries(
      Object.entries(active[other]).filter(([token]) => !isSharedToken(token)))
    onChange({
      active: active.id,
      themes: themes.map((t) =>
        (t.id === active.id ? { ...t, [mode]: {}, [other]: keptOther } : t)),
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
    if (!parsed) { window.alert(tr('appear.notATheme')); return }
    if (themes.length >= MAX_THEMES) { window.alert(tr(AT_CAP, { max: MAX_THEMES })); return }
    onChange({ active: parsed.id, themes: [...themes, parsed] })
  }

  // What each control shows: the override if there is one, else the shipped value.
  const current = useMemo(() => {
    // `themeTokens`, not `active[mode]`: that is what the page applies, and a
    // theme saved before the split carries a shared token in one map only.
    // Reading it raw here would show the shipped value in the control while the
    // page painted the override — the panel and the screen disagreeing.
    const overrides = active ? themeTokens(active, mode) : {}
    const out: ThemeTokens = {}
    for (const token of Object.keys(TOKENS)) {
      out[token] = overrides[token] ?? defaultValue(token, mode)
    }
    return out
  }, [active, mode])

  // A preset's own values are not overrides — nothing of the user's is in play,
  // so every per-token reset is inert and the counter has nothing to count.
  const overridden = isPreset ? {} : (active ? themeTokens(active, mode) : {})

  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal appearance-modal" role="dialog"
        aria-label={tr('appear.title')} aria-modal="true">
        <div className="modal-head">
          <span className="modal-title">{tr('appear.title')}</span>
          <button className="icon-btn" aria-label={tr('common.close')} onClick={onClose}>✕</button>
        </div>

        {/* ---- theme ---- */}
        <div className="appear-bar">
          <select className="input" value={active?.id ?? ''} aria-label={tr('appear.theme')}
            onChange={(e) => selectTheme(e.target.value)}>
            {/* Outside every group, and first: the way back is never buried. */}
            <option value="">{tr('appear.smylteDefault')}</option>
            <optgroup label={tr('appear.builtIn')}>
              {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </optgroup>
            {themes.length > 0 && (
              <optgroup label={tr('appear.yourThemes')}>
                {themes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </optgroup>
            )}
          </select>
          <button className="btn ghost" onClick={saveAs} disabled={!active}>
            {tr('appear.duplicate')}
          </button>
          <button className="btn ghost" onClick={() => { setName(active?.name ?? ''); setRenaming(true) }}
            disabled={!active || isPreset}>{tr('appear.rename')}</button>
          <button className="btn ghost" onClick={exportTheme} disabled={!active}>
            {tr('appear.export')}
          </button>
          <button className="btn ghost" onClick={() => fileRef.current?.click()}>
            {tr('appear.import')}
          </button>
          <input ref={fileRef} type="file" accept="application/json,.json" hidden
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) importTheme(f)
              e.target.value = ''
            }} />
        </div>

        {renaming && active && !isPreset && (
          <div className="appear-bar">
            <input className="input" value={name} autoFocus maxLength={MAX_NAME_LEN}
              aria-label={tr('appear.themeName')} onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { rename(name); setRenaming(false) } }} />
            <button className="btn" onClick={() => { rename(name); setRenaming(false) }}>
              {tr('common.save')}
            </button>
            <button className="btn ghost" onClick={() => setRenaming(false)}>
              {tr('common.cancel')}
            </button>
          </div>
        )}

        <p className="hintline">
          {isPreset
            ? tr('appear.presetHint', { name: active!.name })
            : active
              ? tr('appear.editingHint')
              : tr('appear.shippedHint')}
        </p>

        {/* ---- which mode am I editing ---- */}
        <div className="appear-modes" role="group" aria-label={tr('appear.editingMode')}>
          {(['light', 'dark'] as Mode[]).map((m) => (
            <button key={m} className={`view-tab ${mode === m ? 'active' : ''}`}
              aria-pressed={mode === m} onClick={() => onMode(m)}>
              {m === 'light' ? tr('appear.light') : tr('appear.dark')}
            </button>
          ))}
          <span className="spacer" />
          <span className="hintline">
            {isPreset
              ? tr('appear.builtInTheme')
              : tr('appear.overrides', {
                count: Object.keys(overridden).length, mode: tr(modeWord),
              })}
          </span>
        </div>

        {/* ---- the tokens ---- */}
        <div className="appear-groups">
          {GROUPS.map((group) => {
            const entries = Object.entries(TOKENS).filter(([, s]) => s.group === group)
            if (!entries.length) return null
            return (
              <section key={group} className="appear-group">
                <div className="menu-head">{tr(GROUP_LABEL[group] ?? group)}</div>
                {entries.map(([token, spec]) => (
                  <TokenRow key={token} token={token} spec={spec}
                    value={current[token]} isOverride={token in overridden}
                    onChange={(v) => edit({ [token]: v })}
                    onClear={() => {
                      if (!active || isPreset) return
                      // Symmetric with `edit`: a shared token was written to
                      // both maps, so clearing it from one alone would leave the
                      // reset arrow visibly inert — the value would go on
                      // resolving from the other mode.
                      const other: Mode = mode === 'dark' ? 'light' : 'dark'
                      const next = { ...active[mode] }
                      delete next[token]
                      const nextOther = { ...active[other] }
                      if (isSharedToken(token)) delete nextOther[token]
                      onChange({
                        active: active.id,
                        themes: themes.map((t) => (t.id === active.id
                          ? { ...t, [mode]: next, [other]: nextOther } : t)),
                      })
                    }} />
                ))}
              </section>
            )
          })}
        </div>

        <div className="modal-actions">
          {/* Neither applies to a preset: there is nothing of the user's to
              clear, and leaving one is just selecting something else. */}
          {active && !isPreset && (
            <button className="btn ghost" onClick={resetMode}>
              {tr('appear.resetMode', { mode: tr(modeWord) })}
            </button>
          )}
          {active && !isPreset && (
            <button className="btn ghost danger" onClick={remove}>{tr('appear.deleteTheme')}</button>
          )}
          <button className="btn" onClick={onClose}>{tr('appear.done')}</button>
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
  const tr = useT()
  return (
    <div className="appear-row">
      <label className="appear-label" htmlFor={`tok${token}`}>
        {tr(spec.label)}
        {spec.hint && <span className="appear-hint">{tr(spec.hint)}</span>}
      </label>
      <div className="appear-control">
        {spec.kind === 'color' && (
          <ColorControl id={token} label={tr(spec.label)} value={value} onChange={onChange} />
        )}
        {spec.kind === 'font' && <FontControl id={token} token={token} value={value} onChange={onChange} />}
        {spec.kind === 'keyword' && <KeywordControl id={token} spec={spec} value={value} onChange={onChange} />}
        {(spec.kind === 'length' || spec.kind === 'scale') &&
          <RangeControl id={token} token={token} spec={spec} value={value} onChange={onChange} />}
        <button className="appear-clear" onClick={onClear} disabled={!isOverride}
          title={tr('appear.resetToken')}
          aria-label={tr('appear.resetNamed', { token: tr(spec.label) })}>↺</button>
      </div>
    </div>
  )
}

function ColorControl({ id, label, value, onChange }: {
  id: string; label: string; value: string; onChange: (v: string) => void
}) {
  const tr = useT()
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
      {/* Named for the token it edits. This said "Pick a color" for every one of
          them, so a screen-reader user tabbing the editor heard the same three
          words fourteen times with no way to tell Background from Accent from
          Rule — and the sibling text field, which has a real label, is the one
          that carries the actual value. */}
      <input type="color" className="appear-swatch" value={swatch}
        aria-label={tr('appear.pickColor', { token: label })}
        onChange={(e) => onChange(e.target.value)} />
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
  const tr = useT()
  const tier = token === '--serif' ? 'serif' : token === '--sans' ? 'sans' : 'mono'
  const choices = FONT_CHOICES[tier]
  // A theme imported with a stack we don't offer still needs a stable option to
  // sit on, rather than silently snapping to the default.
  const known = choices.some((c) => c.stack === value)
  return (
    <select id={`tok${id}`} className="input" value={known ? value : ''}
      onChange={(e) => { ensureFont(e.target.value); onChange(e.target.value) }}>
      {!known && (
        <option value="">
          {tr('appear.customFont', { family: value.split(',')[0].replace(/"/g, '') })}
        </option>
      )}
      {choices.map((c) => <option key={c.label} value={c.stack}>{c.label}</option>)}
    </select>
  )
}

/** A closed set of CSS keywords — the token's `values` and nothing else. */
function KeywordControl({ id, spec, value, onChange }: {
  id: string; spec: TokenSpec; value: string; onChange: (v: string) => void
}) {
  const tr = useT()
  const choices = spec.values ?? []
  return (
    <select id={`tok${id}`} className="input" value={value}
      onChange={(e) => onChange(e.target.value)}>
      {choices.map((v) => (
        <option key={v} value={v}>
          {spec.valueLabels?.[v] ? tr(spec.valueLabels[v]) : v}
        </option>
      ))}
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
