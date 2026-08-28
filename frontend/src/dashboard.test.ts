import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  COLS, DEFAULT_LAYOUT, MODULE_KINDS, MODULE_SPECS,
  addModule, clampToGrid, layoutRows, moveModule, overlaps, packDown,
  pxToCellDelta, removeModule, resizeModule, sanitizeLayout,
  type DashboardModule,
} from './dashboard'

const mod = (o: Partial<DashboardModule> = {}): DashboardModule => ({
  id: 'a', kind: 'today', x: 0, y: 0, w: 4, h: 4, ...o,
})

/** No two modules in `mods` may share a cell — the invariant every mutation keeps. */
function noOverlaps(mods: DashboardModule[]): boolean {
  for (let i = 0; i < mods.length; i++) {
    for (let j = i + 1; j < mods.length; j++) {
      if (overlaps(mods[i], mods[j])) return false
    }
  }
  return true
}

describe('overlaps', () => {
  it('detects a shared cell', () => {
    expect(overlaps(mod(), mod({ id: 'b', x: 2, y: 2 }))).toBe(true)
  })

  it('treats touching edges as clear', () => {
    expect(overlaps(mod(), mod({ id: 'b', x: 4 }))).toBe(false)
    expect(overlaps(mod(), mod({ id: 'b', y: 4 }))).toBe(false)
  })
})

describe('clampToGrid', () => {
  it('keeps a module inside the 12 columns', () => {
    expect(clampToGrid(mod({ x: 20, w: 4 })).x).toBe(COLS - 4)
    expect(clampToGrid(mod({ x: -5 })).x).toBe(0)
    expect(clampToGrid(mod({ w: 99 })).w).toBe(COLS)
  })

  it('never shrinks a module below what its content needs', () => {
    const spec = MODULE_SPECS.mini_calendar
    const m = clampToGrid(mod({ kind: 'mini_calendar', w: 1, h: 1 }))
    expect(m.w).toBe(spec.minW)
    expect(m.h).toBe(spec.minH)
  })

  it('rounds fractional cells that a mid-drag pointer can produce', () => {
    const m = clampToGrid(mod({ x: 2.4, y: 3.6, w: 4.2, h: 5.5 }))
    expect([m.x, m.y, m.w, m.h]).toEqual([2, 4, 4, 6])
  })
})

describe('packDown', () => {
  it('pushes a collision downward instead of refusing it', () => {
    const out = packDown([mod({ id: 'a' }), mod({ id: 'b', x: 2, y: 1 })])
    expect(noOverlaps(out)).toBe(true)
  })

  it('floats modules up into empty space', () => {
    const out = packDown([mod({ id: 'a', y: 30 })])
    expect(out[0].y).toBe(0)
  })

  it('closes the hole left when a module above is removed', () => {
    const start = packDown([mod({ id: 'a', y: 0, h: 4 }), mod({ id: 'b', y: 4, h: 4 })])
    const after = removeModule(start, 'a')
    expect(after.find((m) => m.id === 'b')!.y).toBe(0)
  })

  it('keeps side-by-side modules on the same row', () => {
    const out = packDown([mod({ id: 'a', x: 0, w: 4 }), mod({ id: 'b', x: 4, w: 4 })])
    expect(out.every((m) => m.y === 0)).toBe(true)
  })

  it('holds the pinned module’s row and moves everything else', () => {
    // The pinned module is the one under the pointer: letting it float would
    // fight the drag.
    const out = packDown([mod({ id: 'a', y: 0 }), mod({ id: 'b', y: 3 })], 'b')
    expect(out.find((m) => m.id === 'b')!.y).toBe(3)
    expect(noOverlaps(out)).toBe(true)
  })

  it('is idempotent — packing a packed layout changes nothing', () => {
    const once = packDown(DEFAULT_LAYOUT)
    expect(packDown(once)).toEqual(once)
  })
})

describe('moveModule', () => {
  it('lands the module where it was dropped', () => {
    const out = moveModule(DEFAULT_LAYOUT, 'm-today', 4, 0)
    expect(out.find((m) => m.id === 'm-today')!.x).toBe(4)
  })

  it('leaves the layout overlap-free wherever it is dropped', () => {
    for (let x = 0; x <= 8; x++) {
      for (let y = 0; y <= 12; y++) {
        expect(noOverlaps(moveModule(DEFAULT_LAYOUT, 'm-today', x, y)), `${x},${y}`).toBe(true)
      }
    }
  })

  it('ignores an unknown id rather than corrupting the layout', () => {
    expect(moveModule(DEFAULT_LAYOUT, 'nope', 3, 3)).toEqual(packDown(DEFAULT_LAYOUT))
  })
})

describe('resizeModule', () => {
  it('applies the new size', () => {
    const out = resizeModule(DEFAULT_LAYOUT, 'm-today', 8, 9)
    const m = out.find((x) => x.id === 'm-today')!
    expect([m.w, m.h]).toEqual([8, 9])
  })

  it('stays overlap-free while growing to full width', () => {
    for (let w = 1; w <= COLS; w++) {
      expect(noOverlaps(resizeModule(DEFAULT_LAYOUT, 'm-today', w, 6)), `w=${w}`).toBe(true)
    }
  })
})

describe('addModule / removeModule', () => {
  it('places a new module without disturbing the others', () => {
    const out = addModule(DEFAULT_LAYOUT, 'quick_add', 'new')
    expect(out).toHaveLength(DEFAULT_LAYOUT.length + 1)
    expect(noOverlaps(out)).toBe(true)
  })

  it('gives a new module its kind’s preferred size', () => {
    const m = addModule([], 'mini_calendar', 'new')[0]
    expect([m.w, m.h]).toEqual([MODULE_SPECS.mini_calendar.w, MODULE_SPECS.mini_calendar.h])
  })

  it('refuses a kind it does not know', () => {
    // @ts-expect-error — deliberately outside the union, as a bad payload would be
    expect(addModule(DEFAULT_LAYOUT, 'nonsense', 'new')).toEqual(DEFAULT_LAYOUT)
  })

  it('removes by id', () => {
    const out = removeModule(DEFAULT_LAYOUT, 'm-today')
    expect(out.some((m) => m.id === 'm-today')).toBe(false)
  })
})

describe('sanitizeLayout', () => {
  it('accepts a well-formed layout', () => {
    expect(sanitizeLayout(DEFAULT_LAYOUT)).toHaveLength(DEFAULT_LAYOUT.length)
  })

  it('drops modules of an unknown kind', () => {
    // The case that matters in practice: a layout saved by a newer build that
    // knows a module this one does not.
    expect(sanitizeLayout([mod(), { ...mod({ id: 'b' }), kind: 'from_the_future' }]))
      .toHaveLength(1)
  })

  it('drops entries with missing or non-numeric geometry', () => {
    expect(sanitizeLayout([
      { id: 'a', kind: 'today', x: 0, y: 0, w: 4 },
      { id: 'b', kind: 'today', x: 'nope', y: 0, w: 4, h: 4 },
      { id: 'c', kind: 'today', x: NaN, y: 0, w: 4, h: 4 },
    ])).toEqual([])
  })

  it('drops duplicate ids, which would collide as React keys', () => {
    expect(sanitizeLayout([mod({ id: 'a' }), mod({ id: 'a', y: 8 })])).toHaveLength(1)
  })

  it('clamps out-of-range geometry rather than discarding the module', () => {
    const [m] = sanitizeLayout([mod({ x: 99, w: 99, h: 9999 })])
    expect(m.x + m.w).toBeLessThanOrEqual(COLS)
  })

  it('survives junk', () => {
    for (const junk of [null, undefined, 'x', 42, {}]) expect(sanitizeLayout(junk)).toEqual([])
  })

  it('returns an overlap-free layout even from overlapping input', () => {
    const out = sanitizeLayout([mod({ id: 'a' }), mod({ id: 'b' }), mod({ id: 'c' })])
    expect(noOverlaps(out)).toBe(true)
  })
})

describe('layoutRows', () => {
  it('measures to the bottom edge of the lowest module', () => {
    expect(layoutRows([mod({ y: 0, h: 4 }), mod({ id: 'b', y: 6, h: 3 })])).toBe(9)
    expect(layoutRows([])).toBe(0)
  })
})

describe('pxToCellDelta', () => {
  it('converts a pixel drag into whole cells', () => {
    const width = 1200                       // 100px per column
    expect(pxToCellDelta(300, 0, width).dx).toBe(3)
    expect(pxToCellDelta(-100, 0, width).dx).toBe(-1)
  })

  it('does not divide by zero before the grid has been measured', () => {
    expect(pxToCellDelta(300, 300, 0).dx).toBe(0)
  })
})

describe('module registry', () => {
  it('gives every kind a spec the picker can render', () => {
    for (const kind of MODULE_KINDS) {
      expect(MODULE_SPECS[kind].label, kind).toBeTruthy()
      expect(MODULE_SPECS[kind].blurb, kind).toBeTruthy()
    }
  })

  it('ships a default layout that is legal by its own rules', () => {
    expect(sanitizeLayout(DEFAULT_LAYOUT)).toEqual(DEFAULT_LAYOUT)
    expect(noOverlaps(DEFAULT_LAYOUT)).toBe(true)
  })

  it('names exactly the kinds the server will accept', () => {
    // The two lists are a MIRROR and the failure when they part is not a module
    // that quietly does not render: `SettingsPatch.dashboard` is validated as a
    // whole, so one unknown kind 422s the entire PUT — taking the theme, the tab
    // order and everything else in the same write down with it. app.py says so
    // in as many words, and this is what makes the claim checkable.
    //
    // Read out of the source rather than duplicated here, so this file is not a
    // third copy of the same list.
    const py = readFileSync(
      resolve(process.cwd(), '../backend/tasksd/app.py'), 'utf8')
    const block = /class DashboardModule\(BaseModel\):[\s\S]*?kind: Literal\[([\s\S]*?)\]/
      .exec(py)
    expect(block, 'DashboardModule.kind not found in app.py').toBeTruthy()
    const serverKinds = [...block![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1])
    expect([...serverKinds].sort()).toEqual([...MODULE_KINDS].sort())
  })
})
