// Two shapes Settings uses to stay short, ported from Søren's tidy.
//
// `Fold` holds the controls most people set once and leave: its summary line
// says what is in force, so a closed fold still answers "what is this set to?"
// without anyone opening it. `HowFold` holds the longer explanation of how
// something behaves, out of the way of the controls but word for word.
//
// Both are <details>: the browser's own disclosure, keyboard and screen reader
// semantics included, and its contents stay mounted while closed, so a field
// half-typed inside one is not lost by folding it.

import { useState, type ReactNode } from 'react'

export function Fold({ summary, defaultOpen = false, open, onOpenChange, className, children }: {
  /** What is in force, in one line. */
  summary: ReactNode
  /** Open on first render, and the user's to toggle afterwards. */
  defaultOpen?: boolean
  /** Controlled instead, for a fold something else has to open. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  className?: string
  children: ReactNode
}) {
  const [own, setOwn] = useState(defaultOpen)
  const isOpen = open ?? own
  return (
    <details className={`menu-fold${className ? ` ${className}` : ''}`} open={isOpen}
      onToggle={(e) => {
        const next = e.currentTarget.open
        if (next === isOpen) return
        setOwn(next)
        onOpenChange?.(next)
      }}>
      <summary>{summary}</summary>
      <div className="menu-fold-body">{children}</div>
    </details>
  )
}

export function HowFold({ title, children }: { title: string, children: ReactNode }) {
  return (
    <details className="menu-fold menu-more">
      <summary>{title}</summary>
      <div className="menu-fold-body"><div className="hintline">{children}</div></div>
    </details>
  )
}
