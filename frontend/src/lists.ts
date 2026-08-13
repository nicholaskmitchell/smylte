// The order task lists are shown in, and the one every picker should use.
//
// `GET /api/lists` sorts by manual calendar-order then name, which is what the
// sidebar's rail is built from — but the sidebar renders it *through* the task
// groups: each group's members in turn, then whatever is left. So the moment a
// group exists, the array's order and the order on screen are two different
// orders, and the "which list" dropdowns were following the one nobody can see.
//
// React-free like tabs.ts and dashboard.ts, so the rule can be tested on its
// own rather than through a rendered sidebar.

import type { List, TaskGroup } from './api'

/**
 * Which group each list belongs to — the first that names it.
 *
 * Groups are a settings blob a user can hand-edit or import, so the same list
 * can appear in two of them. Sidebar.tsx resolves that by first-wins, and this
 * has to resolve it the same way or a list would render in one place and sort
 * as though it were in another.
 */
function groupOf(groups: TaskGroup[]): Map<string, string> {
  const m = new Map<string, string>()
  for (const g of groups) {
    for (const id of g.lists) if (!m.has(id)) m.set(id, g.id)
  }
  return m
}

/**
 * `lists` in the order the sidebar shows them: each group's members in group
 * order, then everything ungrouped.
 *
 * Order *within* a section is left exactly as it arrived — that is the server's
 * own sort, and the thing drag-reorder persists. A group naming a list that no
 * longer exists contributes nothing, and every list appears exactly once
 * whatever the groups say, so this can never add or drop a row.
 */
export function orderLists(lists: List[], groups: TaskGroup[]): List[] {
  if (!groups.length) return lists
  const owner = groupOf(groups)
  const out: List[] = []
  for (const g of groups) out.push(...lists.filter((l) => owner.get(l.id) === g.id))
  out.push(...lists.filter((l) => !owner.has(l.id)))
  return out
}
