// A date or time field that opens the DEVICE'S OWN picker when you tap it.
//
// Every date and time field in this app is already a native `<input type=date>`,
// `type=time` or `type=datetime-local` — the right choice, and the reason the
// pickers look and behave like the rest of the phone rather than like a widget
// somebody built. What they were missing is the gesture people actually make.
//
// In Chrome and Edge — Android included — tapping the FIELD does not open the
// picker. It puts a caret in one of the segments and waits for you to type
// "03", "15", "2026". The calendar only appears from the small indicator glyph
// at the trailing edge: a target a few millimetres wide, sitting inside a
// control the whole width of a modal, with nothing about it saying it is the
// part that matters. So the ordinary reading of "tap the date field" —
// especially on a phone, where typing a date through a segmented field is the
// slowest thing on the screen — got a blinking cursor.
//
// `HTMLInputElement.showPicker()` is the platform's answer to exactly this, and
// it is the whole of what this component adds: on click, ask the browser to show
// whatever it would have shown had the glyph been pressed. Chrome and Edge open
// their calendar, Firefox opens its, Safari on iOS and Android's Chrome open the
// OS wheel or dial. Nothing here draws a picker of its own — there is no
// calendar in this file, and that is the point of it.
//
// THE FIELD IS STILL A FIELD. Typing works exactly as before, the segments still
// accept a keyboard, `min`/`max` still bound the picker, and the browser's own
// glyph is untouched. This is strictly an added way in, which is why it is bound
// to `click` and not to `focus`: reaching a field with Tab is not asking for a
// popup over it, and a keyboard user who wanted one has Alt+Down and F4 already.
//
// Pressing the browser's own glyph fires a click on the input as well, so this
// asks for a picker that is already opening. That is a no-op rather than a
// toggle: "show the picker, if applicable" has no close arm in the spec, and
// Chromium's implementation returns early when the popup is already up. There
// is deliberately no attempt to detect the glyph and skip — it is a shadow-DOM
// pseudo-element, so the only test available is arithmetic on the click's offset
// against the field's width, which is a guess about someone else's rendering.
//
// It is also why every failure here is silent. `showPicker` is absent on older
// browsers (optional call), throws `NotAllowedError` without transient
// activation, and throws `InvalidStateError` for an input type that has no
// picker — and in every one of those cases the field behaves precisely as it did
// before this component existed. There is nothing to report and nothing to fall
// back to.

import type { InputHTMLAttributes } from 'react'

/** The one place that asks. Guarded twice — see the header. */
function openPicker(el: HTMLInputElement): void {
  try {
    el.showPicker?.()
  } catch {
    /* no picker, no activation, or a browser that has never heard of it */
  }
}

/**
 * A drop-in for `<input type="date|time|datetime-local">`.
 *
 * Every prop is forwarded untouched, so a call site reads exactly as it did as a
 * bare input; the only thing it cannot do is forget the picker. `date-time-input.test.tsx`
 * pins that by grepping the components for raw date inputs, the same way
 * `modal-contract.test.tsx` pins the dialog contract — a rule that lives in one
 * component and is applied by remembering to import it is a rule with a
 * half-life.
 */
export function DateTimeInput({ onClick, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...rest}
      onClick={(e) => {
        openPicker(e.currentTarget)
        // The caller's own handler still runs, and runs AFTER: none of them
        // needs the picker not to be open, and one that did would be free to
        // close it.
        onClick?.(e)
      }}
    />
  )
}
