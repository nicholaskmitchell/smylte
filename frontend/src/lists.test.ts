import { describe, expect, it } from 'vitest'
import { orderLists } from './lists'
import type { List, TaskGroup } from './api'

const list = (id: string): List => ({
  id, href: `/${id}/`, name: id.toUpperCase(), is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
})

const ids = (ls: List[]) => ls.map((l) => l.id)
const group = (id: string, lists: string[]): TaskGroup => ({ id, name: id, lists })

describe('orderLists', () => {
  const all = [list('a'), list('b'), list('c'), list('d')]

  it('returns the input untouched when nothing is grouped', () => {
    expect(ids(orderLists(all, []))).toEqual(['a', 'b', 'c', 'd'])
  })

  it('walks the groups in order, then the ungrouped remainder', () => {
    const groups = [group('g1', ['c']), group('g2', ['a'])]
    expect(ids(orderLists(all, groups))).toEqual(['c', 'a', 'b', 'd'])
  })

  it('keeps the server order inside a group', () => {
    // Within a section the array order stands — that is the manual
    // calendar-order the sidebar renders and drag-reorder persists.
    expect(ids(orderLists(all, [group('g1', ['d', 'b'])]))).toEqual(['b', 'd', 'a', 'c'])
  })

  it('places a list named by two groups once, under the first', () => {
    // Groups are a hand-editable blob, so this is reachable — and the sidebar
    // resolves it first-wins, so a second answer here would sort a row as
    // though it lived somewhere it is not rendered.
    const groups = [group('g1', ['b']), group('g2', ['b', 'a'])]
    expect(ids(orderLists(all, groups))).toEqual(['b', 'a', 'c', 'd'])
  })

  it('ignores a group naming a list that no longer exists', () => {
    const groups = [group('g1', ['gone']), group('g2', ['a'])]
    expect(ids(orderLists(all, groups))).toEqual(['a', 'b', 'c', 'd'])
  })

  it('never adds or drops a row, whatever the groups say', () => {
    const groups = [group('g1', ['a', 'a', 'ghost']), group('g2', ['a', 'c'])]
    const out = orderLists(all, groups)
    expect(out).toHaveLength(all.length)
    expect([...ids(out)].sort()).toEqual(['a', 'b', 'c', 'd'])
  })

  it('handles every list being grouped', () => {
    const groups = [group('g1', ['d', 'c']), group('g2', ['b', 'a'])]
    expect(ids(orderLists(all, groups))).toEqual(['c', 'd', 'a', 'b'])
  })

  it('leaves an empty list set alone', () => {
    expect(orderLists([], [group('g1', ['a'])])).toEqual([])
  })
})
