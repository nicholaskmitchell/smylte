// A FOLD FOLLOWS ITS TASK TO ANOTHER LIST.
//
// `collapsed_tasks` keys a fold by (list, uid), the way every task map in the
// app is keyed, so a task moved to another list came back unfolded under its
// new key. Nothing is drawn here. It lives beside the data rather than in the
// Tasks pane because moves happen where the pane is not mounted: from the
// calendar's task editor, over MCP, or in another client while the owner is on
// another tab. App renders it inside `DataProvider`, which holds every task of
// every list whichever tab is open.
//
// Two sources, because neither sees every move:
//
// * A MOVE THIS APP MADE is announced by `moveTask` (`onTasksMoved`) with
//   every uid that went, and is applied as said. That covers the retry that
//   finds the task in both lists and only takes the old row away, where the
//   data shows nothing arriving.
// * A MOVE MADE ELSEWHERE shows only in the data, so it is inferred, and
//   narrowly: a folded key that was live on the previous pass and is gone now,
//   while exactly one key with its uid has just appeared. Everything else that
//   makes a key look dead is left alone: a view that is behind the account
//   (another device re-keyed first), a cache seed before the fetch, a list
//   that failed to load, or a deleted task whose uid an unrelated task in
//   another list also has, which was already there. The same rule puts a
//   fold back when a failed move puts its row back.
//
// Both write through `onChange`, which saves the setting, and both read the
// latest folds through a ref, so a fold made while a move was in flight is not
// overwritten by the value from before it.
import { useEffect, useRef } from 'react'
import { useTaskData } from '../data'
import { taskKey } from '../order'

const SEP = '\u0000'

export function FoldFollower({ collapsed, onChange }: {
  collapsed: string[]
  onChange: (next: string[]) => void
}) {
  const { tasks, loaded, onTasksMoved } = useTaskData()
  const latest = useRef(collapsed)
  latest.current = collapsed

  const rekey = (map: Map<string, string>) => {
    const cur = latest.current
    if (!cur.some((k) => map.has(k))) return
    const next = [...new Set(cur.map((k) => map.get(k) ?? k))]
    latest.current = next
    onChange(next)
  }

  useEffect(() => onTasksMoved((from, to, uids) => {
    rekey(new Map(uids.map((u) => [`${from}${SEP}${u}`, `${to}${SEP}${u}`])))
    // `rekey` reads only refs and `onChange`, so the subscription need not
    // churn on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [onTasksMoved, onChange])

  const seenLive = useRef<Set<string> | null>(null)
  useEffect(() => {
    if (!loaded) return
    const live = new Set(tasks.map(taskKey))
    const before = seenLive.current
    seenLive.current = live
    if (!before) return
    const arrived = new Map<string, string[]>()
    for (const k of live) {
      if (before.has(k)) continue
      const uid = k.slice(k.indexOf(SEP) + 1)
      arrived.set(uid, [...(arrived.get(uid) ?? []), k])
    }
    if (arrived.size === 0) return
    const map = new Map<string, string>()
    for (const k of latest.current) {
      const at = k.indexOf(SEP)
      if (at < 0 || live.has(k) || !before.has(k)) continue
      const to = arrived.get(k.slice(at + 1)) ?? []
      if (to.length === 1) map.set(k, to[0])
    }
    if (map.size > 0) rekey(map)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, tasks])

  return null
}
