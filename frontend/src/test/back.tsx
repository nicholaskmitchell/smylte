// Android's Back, for the suites of the components that are layers (layers.ts).
// The page hears Back as a call to `backTopLayer`; these are that call and the
// prompt it may open, so a suite can press Back next to the Escape it already
// presses.

import type { ReactElement } from 'react'
import { act } from '@testing-library/react'
import { DiscardPrompt } from '../components/DiscardPrompt'
import { backTopLayer } from '../layers'

/** Press Back, as the host's `back` event does, and say whether a layer took it. */
export function pressBack(): boolean {
  let taken = false
  act(() => { taken = backTopLayer() })
  return taken
}

/** `ui` with the one "Discard changes?" dialog App mounts beside it. */
export function withPrompt(ui: ReactElement): ReactElement {
  return <>{ui}<DiscardPrompt /></>
}
