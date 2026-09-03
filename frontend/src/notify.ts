// A browser notification at the end of an interval — the one alert that
// reaches the owner when the window is behind something else, which while
// working is the ordinary case.
//
// Net-new surface for an app that has kept every notification policy
// server-side, in Telegram, on purpose. It earns its place because it is the
// opposite kind of message: the Telegram rules exist for things you cannot
// recover by opening the app later, and this one is for a thing you cannot
// recover by opening the app NOW — the app is open, the tab is just not the one
// in front. Nothing here is scheduled, nothing is sent while the surface is
// closed, and nothing leaves the device.
//
// Permission is asked for inside a gesture (the Settings switch, or Start with
// the switch already on) and never on load — a page that asks on arrival is
// the page everyone has learned to say no to. Every call is guarded: jsdom and
// a kiosk browser have no `Notification`, and its absence must cost the
// surface nothing.

type Perm = 'default' | 'granted' | 'denied' | 'unsupported'

type NotificationCtor = {
  new (title: string, options?: { body?: string; tag?: string; silent?: boolean }): { close(): void }
  permission: NotificationPermission
  requestPermission(): Promise<NotificationPermission>
}

function ctor(): NotificationCtor | null {
  const N = (globalThis as { Notification?: NotificationCtor }).Notification
  return typeof N === 'function' ? N : null
}

export function notifyPermission(): Perm {
  const N = ctor()
  if (!N) return 'unsupported'
  try { return N.permission } catch { return 'unsupported' }
}

/** Ask, from a gesture. Resolves to the answer; never throws. */
export async function requestNotify(): Promise<Perm> {
  const N = ctor()
  if (!N) return 'unsupported'
  try { return await N.requestPermission() } catch { return notifyPermission() }
}

const TAG = 'smylte-focus'

/** Show one, replacing the last — a phase that ended twice (two windows) is
 *  one piece of news. Silent: the chime is the sound, and a second one from
 *  the OS on top of it would be the app saying the same thing twice. */
export function showNotify(title: string, body: string): boolean {
  const N = ctor()
  if (!N || notifyPermission() !== 'granted') return false
  try {
    new N(title, { body, tag: TAG, silent: true })
    return true
  } catch { return false }
}
