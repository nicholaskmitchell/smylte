// What a view needs to know about the frame it is drawn in.
//
// Under the sidebar layout, Tasks and Calendar do not draw their own sidebar:
// they lend their collections (the lists, the calendars and the tasks-on-the-
// calendar section) to the app sidebar, which renders them under the views.
// The collections stay OWNED by the view — its fetches, its local panes
// (completed, parked), its drawer and its edit dialogs are exactly the code
// Classic runs — and only where they are mounted changes. That is a portal
// into a slot the shell provides, not a second copy of the sidebar held in
// App, which is what keeps Classic the same component tree it always was.
import { createContext, useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useIsMobile } from './hooks'
import type { Layout } from './layout'

export interface Shell {
  layout: Layout
  /** The app sidebar's collections slot, once it is in the DOM. Null under
   *  Classic, on a phone (which has no app sidebar), and for the first commit
   *  of the sidebar layout before the slot's ref lands. */
  navSlot: HTMLElement | null
  /** The app sidebar is folded to its rail. Under Classic this is the same
   *  account flag the per-view sidebars read. */
  navCollapsed: boolean
}

// Classic is the default for a reason, not for convenience: a view rendered
// with no shell around it — every component test in this tree, and anything
// mounted outside the app — has no app sidebar to lend its collections to, and
// drawing its own is the only way they stay reachable. Classic is exactly that.
const ShellCtx = createContext<Shell>({ layout: 'classic', navSlot: null, navCollapsed: false })

export const ShellProvider = ShellCtx.Provider

export function useShell(): Shell {
  return useContext(ShellCtx)
}

/** Whether this view's collections live in the app sidebar right now: the
 *  sidebar layout, on a screen wide enough to have one. A phone under either
 *  layout keeps the per-view trigger bar and drawer. */
export function useEmbeddedCollections(): boolean {
  const { layout } = useShell()
  const isMobile = useIsMobile()
  return layout === 'sidebar' && !isMobile
}

/**
 * Where a view's collection sidebar renders.
 *
 * Embedded, it portals into the app sidebar's slot — or renders nothing for
 * the one commit before that slot exists, rather than drawing inline and then
 * jumping (the slot's ref lands in the same commit, and the re-render it
 * triggers runs before the browser paints). Otherwise the children render in
 * place, which under Classic is the very element tree it always was: a
 * fragment adds no node.
 */
export function NavCollections({ children }: { children: ReactNode }) {
  const { navSlot } = useShell()
  const embedded = useEmbeddedCollections()
  if (!embedded) return <>{children}</>
  return navSlot ? createPortal(children, navSlot) : null
}
