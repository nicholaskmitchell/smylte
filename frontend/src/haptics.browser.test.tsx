// The Android client's haptics (android.ts), in real browser engines.
//
// What jsdom cannot say is how the engines really activate controls: a click
// on a label is forwarded to its checkbox, and the checkbox is flipped before
// the event is dispatched. It also cannot say how React behaves when the app
// commits inside the click itself, which is what the capture-phase listener
// must read the state before. Production-shaped mount (`createRoot` +
// `StrictMode` under a `.shell` host, as main.tsx does), in Chromium AND WebKit.
import { StrictMode, useState } from 'react'
import { flushSync } from 'react-dom'
import { createRoot, type Root } from 'react-dom/client'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { startAndroidHost } from './android'

const haptic = vi.fn()

beforeAll(() => {
  vi.stubGlobal('SmylteAndroid', { haptic })
  startAndroidHost()
})
afterAll(() => { vi.unstubAllGlobals() })

let root: Root | null = null
let host: HTMLElement | null = null
afterEach(() => {
  root?.unmount(); host?.remove(); root = null; host = null
  haptic.mockClear()
})

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function until(what: string, ok: () => boolean) {
  for (let i = 0; i < 200 && !ok(); i++) await sleep(10)
  expect(ok(), what).toBe(true)
}

function Check() {
  const [on, setOn] = useState(false)
  return (
    <button type="button" className="check" aria-label="Done" aria-pressed={on}
      onClick={() => flushSync(() => setOn((v) => !v))} />
  )
}

function Busy() {
  const [on, setOn] = useState(false)
  return (
    <label>
      <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} />
      <span>Busy</span>
    </label>
  )
}

function mount(children: React.ReactNode) {
  host = document.createElement('div')
  host.className = 'shell'
  document.body.appendChild(host)
  root = createRoot(host)
  root.render(<StrictMode>{children}</StrictMode>)
}

describe('haptics in a real engine', () => {
  it('a check plays confirm then toggleOff, even when the app commits inside the click', async () => {
    mount(<Check />)
    await until('the check mounts', () => !!document.querySelector('.check'))
    const check = document.querySelector<HTMLElement>('.check')!
    check.click()
    check.click()
    expect(haptic.mock.calls).toEqual([['confirm'], ['toggleOff']])
  })

  it('a label plays once, for the state its checkbox goes to', async () => {
    mount(<Busy />)
    await until('the label mounts', () => !!document.querySelector('label span'))
    const span = document.querySelector<HTMLElement>('label span')!
    span.click()
    span.click()
    expect(haptic.mock.calls).toEqual([['toggleOn'], ['toggleOff']])
  })

  it('a disabled check plays nothing', async () => {
    mount(<button type="button" className="check" aria-label="Done" aria-pressed={false} disabled />)
    await until('the check mounts', () => !!document.querySelector('.check'))
    document.querySelector<HTMLElement>('.check')!.click()
    expect(haptic).not.toHaveBeenCalled()
  })
})
