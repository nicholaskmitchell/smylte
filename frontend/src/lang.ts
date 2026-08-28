// Which language the app speaks, and which locale it formats dates in.
//
// React-free like time.ts, tabs.ts and order.ts, so the rules can be tested
// directly rather than through a rendered view. The catalogues themselves live
// in `i18n/`; this module is only the choice and what follows from it.
//
// ── why a setting and not the browser's ────────────────────────────────────
//
// `navigator.language` is what the DEVICE was set up in, which is a different
// question from what its owner wants to read an app in — a German speaker on a
// work laptop imaged in English is the ordinary case, not the edge one. Every
// other display preference here is account-synced (the clock, the theme, the
// tab order), and this one follows them: chosen once, and the same on the
// phone. The browser's answer is still used, but as a hint about REGION rather
// than about language — see `localeFor`.

/** The languages the app is translated into. Adding one means adding a
 *  catalogue under `i18n/` and nothing else; `i18n.test.ts` checks that every
 *  catalogue answers every key. */
export type Language = 'en' | 'de'

export const LANGUAGES: readonly Language[] = ['en', 'de']

/** The language a stored setting falls back to, and the one every catalogue is
 *  checked against — English is the source text, so a key it lacks is a key
 *  nobody wrote rather than a translation nobody did. */
export const DEFAULT_LANGUAGE: Language = 'en'

// Settings are a JSON blob a user can hand-edit or import, so the stored value
// is re-validated on the way in rather than trusted — the same discipline
// `isTimeFormat` and `sanitizeAppearance` apply to theirs.
export function isLanguage(v: unknown): v is Language {
  return v === 'en' || v === 'de'
}

/** What each language calls ITSELF.
 *
 *  An endonym, not a translation: a picker that offers "German" to someone who
 *  cannot read the English it is written in has failed at the one moment it
 *  matters. Every list of languages worth using does this, and it is also why
 *  these two strings are NOT in the catalogues — they must read the same
 *  whichever language is currently in force. */
export const LANGUAGE_LABEL: Readonly<Record<Language, string>> = {
  en: 'English',
  de: 'Deutsch',
}

export function languageLabel(l: Language): string {
  return LANGUAGE_LABEL[l] ?? LANGUAGE_LABEL[DEFAULT_LANGUAGE]
}

/**
 * The BCP-47 tag to format dates, times and lists with.
 *
 * NOT simply the language tag, and the difference is the point. A date's ORDER,
 * its separators and its clock are regional, not linguistic: an English speaker
 * in London reads 28/08/2026 and one in Chicago reads 8/28/2026, and the app
 * has always got that right by passing `undefined` and letting the browser
 * answer. Replacing that with a bare `'en'` would quietly move every UK account
 * to American dates on the day this shipped — a regression for people who never
 * touched the setting.
 *
 * So the browser's own list is consulted FIRST and used whenever it agrees with
 * the chosen language: `de-AT` is kept for an Austrian who picks Deutsch, and
 * `en-GB` for a Londoner who leaves it at English. Only when the device has
 * nothing in that language does this fall back to the bare tag, which is the
 * honest answer — a German UI dated in American order is worse than one dated
 * in the language's own default.
 *
 * `navigator.languages` rather than `navigator.language` because the first is
 * the ordered preference list and the second is only its head: a device set to
 * English with German second is exactly the account this setting exists for.
 */
export function localeFor(
  lang: Language,
  // A parameter so the rule is testable without a browser, and so the Windows
  // client's WebView — whose list can differ from the OS's — is not a special
  // case. Defaults to what the browser says, which is what every caller wants.
  preferred: readonly string[] = typeof navigator === 'undefined'
    ? [] : (navigator.languages ?? [navigator.language].filter(Boolean)),
): string {
  for (const tag of preferred) {
    // The base subtag, case-insensitively: BCP-47 is case-insensitive and
    // `navigator.languages` is not guaranteed to be normalised.
    if (typeof tag === 'string' && tag.toLowerCase().split('-')[0] === lang) return tag
  }
  return lang
}
