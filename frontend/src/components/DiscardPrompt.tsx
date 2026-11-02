// "Discard changes?", for whichever layer Back asked about (layers.ts). Mounted
// once, by App. Only the Android client's Back opens it: Escape, ✕ and the scrim
// close an editor exactly as they always have.

import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useEscape } from '../hooks'
import { useT } from '../i18n'
import { useDiscardAsk, useLayer, type DiscardAsk } from '../layers'

/** How long taps are swallowed after the question closes. */
export const SHIELD_MS = 400

export function DiscardPrompt() {
  const ask = useDiscardAsk()
  // On a phone the question is a bottom sheet over the editor's own, so "Keep
  // editing" sits exactly where the editor's Save or Add does, and the second
  // tap of an impatient double tap saved the form the user had just chosen to
  // keep editing. A transparent shield takes taps for a moment after the
  // question goes. A layout effect, so it is in the DOM in the same commit that
  // removes the question.
  const [shield, setShield] = useState(false)
  const asked = useRef(false)
  useLayoutEffect(() => {
    if (ask) { asked.current = true; return }
    if (!asked.current) return
    asked.current = false
    setShield(true)
    const t = setTimeout(() => setShield(false), SHIELD_MS)
    return () => clearTimeout(t)
  }, [ask])
  if (ask) return <DiscardDialog ask={ask} />
  return shield
    ? (
      <div className="discard-shield" aria-hidden="true"
        // Not focus: "Keep editing" has just put it back in the field. Not
        // App's outside press either, which closes Settings.
        onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
        onClick={(e) => e.stopPropagation()} />
    )
    : null
}

function DiscardDialog({ ask }: { ask: DiscardAsk }) {
  const tr = useT()
  const title = useId()
  const body = useId()
  // Whether the press that started this click landed on the scrim itself.
  const scrimPress = useRef(false)
  // A layer of its own, above the one it asks about: Back here keeps editing,
  // so a second Back can never be the one that discards.
  const dialogRef = useRef<HTMLDivElement>(null)
  useLayer(ask.keep, { dialog: dialogRef })
  // Capture phase, stopped there: the editor underneath answers Escape at the
  // window by closing, which would throw away the very input this asks about.
  useEscape(ask.keep, { capture: true })
  // Tab stays on the two answers. The form underneath is still in the tab
  // order, so Shift+Tab, Shift+Tab, Enter reached its Add and created the
  // half-typed task this asks about.
  const discardRef = useRef<HTMLButtonElement>(null)
  const keepRef = useRef<HTMLButtonElement>(null)
  const wrapTab = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab') return
    const at = document.activeElement
    const next = e.shiftKey
      ? (at === discardRef.current || at === e.currentTarget ? keepRef.current : null)
      : (at === keepRef.current ? discardRef.current : null)
    if (!next) return
    e.preventDefault()
    next.focus()
  }

  return (
    <div className="overlay discard-overlay"
      onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
      onClick={(e) => {
        if (e.target === e.currentTarget && scrimPress.current) ask.keep()
        scrimPress.current = false
      }}>
      <div className="modal" ref={dialogRef} tabIndex={-1} role="alertdialog" aria-modal="true"
        aria-labelledby={title} aria-describedby={body} onClick={(e) => e.stopPropagation()}
        onKeyDown={wrapTab}>
        <div className="modal-head">
          <span className="modal-title" id={title}>{tr('discard.title')}</span>
        </div>
        <div className="hintline" id={body}>{tr('discard.body')}</div>
        <div className="modal-actions">
          <button className="btn ghost danger" ref={discardRef} onClick={ask.discard}>
            {tr('discard.discard')}
          </button>
          <span className="spacer" />
          <button className="btn" ref={keepRef} autoFocus onClick={ask.keep}>{tr('discard.keep')}</button>
        </div>
      </div>
    </div>
  )
}
