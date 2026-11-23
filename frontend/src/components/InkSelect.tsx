// A <select> that Field notes draws its caret on.
//
// The select is the same element it always was: every prop goes to it, so a
// call site reads as a bare <select> did, and its label, value, keyboard and
// native list are the browser's; the tests that find it by role or label find
// it. Beside it is the pen's caret (IconInk), aria-hidden. The two sit in
// `.ink-field`, which under the presets is no box at all (app.css, `display:
// contents`), so they lay out exactly as before and the caret is hidden. Under
// Field notes the wrapper is the select's box in its row, the select fills it
// and the caret is drawn over its trailing end (fieldnotes.css, "fields draw
// their glyph"). The CSP refuses a data-URI image, so the caret cannot be a
// background, and a select has no ::after to draw it on.
//
// controls-ink.test.ts holds every select in the components to this.
import type { SelectHTMLAttributes } from 'react'
import { IconInk } from './Marks'

export function InkSelect(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className="ink-field">
      <select {...props} />
      <IconInk icon="caret" />
    </span>
  )
}
