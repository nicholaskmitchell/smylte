// "Discard changes?", for whichever layer Back asked about (layers.ts). Mounted
// once, by App. Only the Android client's Back opens it: Escape, ✕ and the scrim
// close an editor exactly as they always have.

import { useId, useRef } from 'react'
import { useEscape } from '../hooks'
import { useT } from '../i18n'
import { useDiscardAsk, useLayer, type DiscardAsk } from '../layers'

export function DiscardPrompt() {
  const ask = useDiscardAsk()
  return ask ? <DiscardDialog ask={ask} /> : null
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

  return (
    <div className="overlay discard-overlay"
      onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
      onClick={(e) => {
        if (e.target === e.currentTarget && scrimPress.current) ask.keep()
        scrimPress.current = false
      }}>
      <div className="modal" ref={dialogRef} tabIndex={-1} role="alertdialog" aria-modal="true"
        aria-labelledby={title} aria-describedby={body} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title" id={title}>{tr('discard.title')}</span>
        </div>
        <div className="hintline" id={body}>{tr('discard.body')}</div>
        <div className="modal-actions">
          <button className="btn ghost danger" onClick={ask.discard}>{tr('discard.discard')}</button>
          <span className="spacer" />
          <button className="btn" autoFocus onClick={ask.keep}>{tr('discard.keep')}</button>
        </div>
      </div>
    </div>
  )
}
