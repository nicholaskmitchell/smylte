// The message catalogues, and the one function that reads them.
//
// React-free on purpose, like `time.ts` and `lang.ts`: what a key resolves to
// is decidable without a render, and `i18n.test.ts` decides it directly. The
// provider that hands `t` to the tree is `../i18n.tsx`.
//
// ── the shape of a message ─────────────────────────────────────────────────
//
// A message is a string with `{name}` placeholders, or — when the sentence
// changes with a count — a record of plural CATEGORIES. The categories are
// `Intl.PluralRules`', not a hand-rolled one/many: English and German happen to
// share the same two ("one" and "other"), so a bare singular/plural pair would
// work for both and break silently on the third language added, which is
// exactly how a translation layer accumulates the assumption that every
// language counts like English. `other` is required and is what an unlisted
// category falls back to.
//
// ── what is NOT in here ────────────────────────────────────────────────────
//
//   * `LANGUAGE_LABEL` — a language names itself the same way whatever the app
//     is currently speaking. See lang.ts.
//   * Anything the SERVER writes. Error text reaches the toast from FastAPI and
//     from the CalDAV client, and translating it would mean either teaching the
//     backend a language or mapping error codes here; both are real work and
//     neither is this. Server errors stay English, and the toast is the only
//     place that shows.
//   * Data. A list called "Einkäufe" is called that in every language.

import { DEFAULT_LANGUAGE, type Language } from '../lang'
import { en } from './en'
import { de } from './de'

/** A message that changes with a count. `other` is the fallback for any
 *  category a catalogue does not spell out. */
export type Plural = { readonly other: string } & Partial<Record<Intl.LDMLPluralRule, string>>
export type Message = string | Plural
export type Catalogue = Readonly<Record<string, Message>>

/** Values for a message's `{placeholders}`. `count` additionally selects the
 *  plural category, which is why it is typed apart from the rest. */
export type Vars = Readonly<Record<string, string | number>> & { count?: number }

export const CATALOGUES: Readonly<Record<Language, Catalogue>> = { en, de }

/** Every key the app can ask for, taken from English — the source text. A key
 *  English does not have is a key nobody wrote, not one nobody translated. */
export type MessageKey = keyof typeof en

const isPlural = (m: Message): m is Plural => typeof m !== 'string'

/**
 * The message for `key` in `lang`, with `{placeholders}` filled in.
 *
 * Falls back to English and then to the key itself, in that order and never
 * further. A missing translation showing the English is the honest degradation
 * — the sentence is still true, just not in the reader's language — while a
 * blank or a raw key is a bug the reader has to work around. `i18n.test.ts`
 * makes the fallback unreachable in a shipped build by requiring both
 * catalogues to answer every key; it stays here for the frame after a key is
 * added and before its translation lands.
 */
export function translate(lang: Language, key: string, vars?: Vars): string {
  const msg = CATALOGUES[lang]?.[key] ?? CATALOGUES[DEFAULT_LANGUAGE][key]
  if (msg === undefined) return key
  let text: string
  if (isPlural(msg)) {
    // `Intl.PluralRules` decides the category, not arithmetic here: "1" is not
    // the only thing that takes a singular in every language, and the whole
    // point of asking the platform is not to encode that belief.
    const n = vars?.count ?? 0
    const cat = new Intl.PluralRules(lang).select(n)
    text = msg[cat] ?? msg.other
  } else {
    text = msg
  }
  if (!vars) return text
  // Only names that were supplied are substituted; an unknown `{name}` is left
  // standing rather than blanked, so a mistyped placeholder is visible in the
  // UI instead of silently eating a word.
  return text.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const v = vars[name]
    if (v === undefined) return whole
    // Numbers through `Intl.NumberFormat`: German writes 1.000 where English
    // writes 1,000, and a count interpolated with `String(n)` would be the one
    // number on a translated screen still written the English way.
    return typeof v === 'number' ? new Intl.NumberFormat(lang).format(v) : v
  })
}
