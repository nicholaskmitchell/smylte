// How long a login lasts, as the Settings menu offers it.
//
// It used to be TASKS_SESSION_TTL in /etc/tasks/tasks.env — a deploy-time
// decision, changed by editing a file and restarting the service. The values
// here are the whole allowlist the server accepts (`_SESSION_TTLS` in app.py);
// anything else is refused with a 422, because this decides how long a session
// survives and the settings blob is hand-editable.
//
// React-free like tabs.ts, so the choice-cycling and the labels can be tested
// without rendering the menu.

/** Ten years. Not an absent expiry: a JWT with no `exp` is immortal, and the
 *  revocation list logout depends on retires entries by their token's own
 *  expiry — so "never" is a long finite life, not an unbounded one. */
export const SESSION_NEVER = 10 * 365 * 24 * 3600

export const SESSION_CHOICES = [
  { s: 24 * 3600, label: '1 day' },
  { s: 7 * 24 * 3600, label: '7 days' },
  { s: 30 * 24 * 3600, label: '30 days' },
  { s: SESSION_NEVER, label: 'Never' },
] as const

/** The deployment's own default, used until the account chooses otherwise.
 *  Matches `config.py`'s fallback so the menu opens on the truth. */
export const SESSION_DEFAULT = 7 * 24 * 3600

export function isSessionTtl(v: unknown): v is number {
  return typeof v === 'number' && SESSION_CHOICES.some((c) => c.s === v)
}

/** What to show for a stored value, falling back to the shipped default. */
export function sessionLabel(ttl: number | null | undefined): string {
  const hit = SESSION_CHOICES.find((c) => c.s === ttl)
  return (hit ?? SESSION_CHOICES.find((c) => c.s === SESSION_DEFAULT)!).label
}

/** The next choice along, wrapping — the menu is a cycling button like the
 *  theme and completed-tasks toggles beside it, not a dropdown. */
export function nextSessionTtl(ttl: number | null | undefined): number {
  const i = SESSION_CHOICES.findIndex((c) => c.s === (isSessionTtl(ttl) ? ttl : SESSION_DEFAULT))
  return SESSION_CHOICES[(i + 1) % SESSION_CHOICES.length].s
}
