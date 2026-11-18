// A line of text that explains the control beside it. Field notes names things
// and does not explain them, so under Field notes the line is not rendered; the
// presets keep it exactly as they always had.
//
// Only for explanatory text. `.hintline` is also the class of units, status
// lines, warnings and empty states, which stay under every design: those do not
// use this component.
import type { ReactNode } from 'react'
import { useFieldNotes } from '../hooks'

export function Hint({ as: Tag = 'div', className = 'hintline', id, children }: {
  as?: 'div' | 'p' | 'span'
  className?: string
  id?: string
  children: ReactNode
}) {
  const fieldNotes = useFieldNotes()
  if (fieldNotes) return null
  return <Tag className={className} id={id}>{children}</Tag>
}
