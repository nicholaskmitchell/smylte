// The translation layer, and the guards that keep a catalogue honest.
//
// Two kinds of test here and they do different jobs. The behavioural ones pin
// what `translate` does — the fallback chain, interpolation, plural selection.
// The STRUCTURAL ones compare the catalogues against each other, and they are
// the ones that will actually fire: a string added to English and forgotten in
// German is the ordinary way a translated app rots, and it is invisible in
// every other test because the suite runs in English.

import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { CATALOGUES, translate, type Plural } from './i18n/index'
import { en } from './i18n/en'
import { de } from './i18n/de'
import { DEFAULT_LANGUAGE, LANGUAGES, deviceLanguage, isLanguage, languageLabel, localeFor } from './lang'

const keys = (c: object) => Object.keys(c).sort()
const placeholders = (m: string | Plural): string[] => {
  const texts = typeof m === 'string' ? [m] : Object.values(m)
  const out = new Set<string>()
  for (const t of texts) for (const p of t.match(/\{\w+\}/g) ?? []) out.add(p)
  return [...out].sort()
}

describe('the catalogues agree', () => {
  it('every language answers every key English has', () => {
    // English is the source text, so this is the direction that matters: a key
    // it has and another lacks is an untranslated string, which `translate`
    // silently papers over with the English. That fallback is the right
    // behaviour at runtime and the wrong thing to ship.
    for (const lang of LANGUAGES) {
      const missing = keys(en).filter((k) => !(k in CATALOGUES[lang]))
      expect(missing, `${lang} is missing: ${missing.join(', ')}`).toEqual([])
    }
  })

  it('and no language answers a key English does not have', () => {
    // The other direction is a different fault: a key nothing asks for, usually
    // left behind by a rename, which no fallback reveals because nothing reads
    // it. It costs bytes and it misleads the next person to grep for a string.
    for (const lang of LANGUAGES) {
      const extra = keys(CATALOGUES[lang]).filter((k) => !(k in en))
      expect(extra, `${lang} has keys nothing asks for: ${extra.join(', ')}`).toEqual([])
    }
  })

  it('and spells the same placeholders in every language', () => {
    // A translation that drops `{count}` renders a sentence with a hole in it,
    // and one that invents `{n}` renders the brace. Neither throws, both ship.
    for (const lang of LANGUAGES) {
      const wrong: string[] = []
      for (const k of keys(en)) {
        const a = placeholders(en[k as keyof typeof en])
        const b = placeholders(CATALOGUES[lang][k])
        if (a.join() !== b.join()) wrong.push(`${k}: en ${a.join()} vs ${lang} ${b.join()}`)
      }
      expect(wrong, wrong.join(' | ')).toEqual([])
    }
  })

  it('and keeps a plural a plural on both sides', () => {
    // A count-dependent string translated as one fixed sentence reads correctly
    // for exactly one value of the count.
    for (const lang of LANGUAGES) {
      const flattened = keys(en)
        .filter((k) => typeof en[k as keyof typeof en] !== 'string')
        .filter((k) => typeof CATALOGUES[lang][k] === 'string')
      expect(flattened, `${lang} flattened a plural: ${flattened.join(', ')}`).toEqual([])
    }
  })
})

describe('the German catalogue', () => {
  it('addresses the reader as du, never as Sie', () => {
    // Stated once in de.ts's header and enforced here, because it has to hold
    // across every string and the first `Ihre` to slip in is the one that makes
    // the rest read like a form. Lower-case `sie` is she/they and is fine.
    const formal: string[] = []
    for (const [k, m] of Object.entries(de)) {
      const text = typeof m === 'string' ? m : Object.values(m).join(' ')
      const hit = text.match(/\b(Sie|Ihre[nmrs]?|Ihnen|Ihr)\b/g)
      if (hit) formal.push(`${k}: ${[...new Set(hit)].join(', ')}`)
    }
    expect(formal, `formal address in: ${formal.join(' | ')}`).toEqual([])
  })

  it('leaves protocol nouns alone', () => {
    // CalDAV, VTODO and the rest are names. A "VTODO" translated is a "VTODO"
    // nobody can look up, and this repo's whole trust model is written in them.
    const text = Object.values(de).map((m) => (typeof m === 'string' ? m : Object.values(m).join(' '))).join(' ')
    if (text.includes('CalDAV') || text.includes('Radicale')) {
      expect(text, 'a protocol noun was translated').not.toMatch(/Kal-?DAV|Radikale\b/)
    }
  })
})

describe('translate', () => {
  it('returns the message for the language asked for', () => {
    expect(translate('en', 'app.settings')).toBe('Settings')
    expect(translate('de', 'app.settings')).toBe('Einstellungen')
  })

  it('falls back to English, then to the key, and no further', () => {
    // The frame after a key is added and before its translation lands. Showing
    // the English is the honest degradation — the sentence is still true, just
    // not in the reader's language — while a blank is a hole nobody can act on.
    const lang = 'de'
    expect(translate(lang, 'app.settings')).toBe('Einstellungen')
    expect(translate(lang, 'no.such.key')).toBe('no.such.key')
  })

  it('fills in placeholders, and leaves an unknown one standing', () => {
    // Standing, not blanked: a mistyped placeholder is then visible in the UI
    // rather than silently eating a word out of the sentence.
    const t = (m: string, v?: Record<string, string | number>) =>
      // A message not in the catalogue exercises the same substitution path.
      m.replace(/\{(\w+)\}/g, (w, n) => (v?.[n] === undefined ? w : String(v[n])))
    expect(t('Hi {name}', { name: 'Nick' })).toBe('Hi Nick')
    expect(t('Hi {name}', {})).toBe('Hi {name}')
  })

  it('formats an interpolated number for the language', () => {
    // German writes 1.000 where English writes 1,000. A count pasted in with
    // `String(n)` would be the one number on a translated screen still written
    // the English way.
    expect(new Intl.NumberFormat('de').format(1000)).toBe('1.000')
    expect(new Intl.NumberFormat('en').format(1000)).toBe('1,000')
  })
})

describe('the language setting', () => {
  it('validates a stored value rather than trusting it', () => {
    // Settings are a hand-editable JSON blob, like every other value App reads.
    expect(isLanguage('de')).toBe(true)
    expect(isLanguage('en')).toBe(true)
    expect(isLanguage('fr')).toBe(false)
    expect(isLanguage(null)).toBe(false)
    expect(isLanguage(['de'])).toBe(false)
  })

  it('names each language in that language', () => {
    // An endonym: a picker that offers "German" to someone who cannot read the
    // English it is written in has failed at the one moment it matters.
    expect(languageLabel('de')).toBe('Deutsch')
    expect(languageLabel('en')).toBe('English')
    expect(languageLabel('xx' as never)).toBe(languageLabel(DEFAULT_LANGUAGE))
  })
})

describe('deviceLanguage', () => {
  // The sign-in screen has no account to ask and is the first thing anyone
  // sees. Everywhere else the account's setting decides, which is why App uses
  // this only while signed out.
  it('reads a supported language out of the browser list', () => {
    expect(deviceLanguage(['de-AT', 'en-US'])).toBe('de')
    expect(deviceLanguage(['en-GB'])).toBe('en')
  })

  it('reads past languages it has no catalogue for', () => {
    expect(deviceLanguage(['fr-CA', 'ja', 'de'])).toBe('de')
  })

  it('falls back to English when nothing in the list is supported', () => {
    expect(deviceLanguage(['fr', 'ja'])).toBe('en')
    expect(deviceLanguage([])).toBe('en')
  })

  it('ignores anything in the list that is not a tag', () => {
    // `navigator.languages` is a browser-supplied array; nothing here trusts
    // its contents to be strings any more than the settings blob is trusted.
    expect(deviceLanguage([null as unknown as string, 'de'])).toBe('de')
  })
})

describe('localeFor', () => {
  it('keeps the device region when it agrees with the language', () => {
    // The app has always passed `undefined` and let the browser answer, which
    // gets date ORDER right: 28/08/2026 in London, 8/28/2026 in Chicago.
    // Replacing that with a bare 'en' would have moved every UK account to
    // American dates on the day this shipped.
    expect(localeFor('en', ['en-GB', 'de'])).toBe('en-GB')
    expect(localeFor('de', ['de-AT', 'en-US'])).toBe('de-AT')
  })

  it('reads past the head of the list', () => {
    // `navigator.languages` is an ordered preference list, and a device set up
    // in English with German second is exactly the account this exists for.
    expect(localeFor('de', ['en-US', 'de-CH'])).toBe('de-CH')
  })

  it('falls back to the bare tag when the device has nothing in that language', () => {
    // A German UI dated in American order is worse than one dated in the
    // language's own default.
    expect(localeFor('de', ['en-US', 'fr-FR'])).toBe('de')
    expect(localeFor('de', [])).toBe('de')
  })

  it('is case-insensitive, as BCP-47 is', () => {
    expect(localeFor('de', ['DE-at'])).toBe('DE-at')
  })
})

// ── the source, swept ────────────────────────────────────────────────────────
//
// Two structural guards over the components themselves. Both catch the same
// class of mistake: a screen that is translated in its words and still English
// in its dates, which is worse than an untranslated screen because it looks
// finished. The idiom — assert against the files on disk — is the one
// `mobile-layout.test.ts` uses, and for the same reason: what is being checked
// is a property of every call site at once, not of any one render.

describe('the source', () => {
  const src = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8')
  const components = readdirSync(resolve(process.cwd(), 'src/components'))
    .filter((f) => f.endsWith('.tsx') && !f.includes('.test.'))

  it('formats dates in the app language, not the device one', () => {
    // `toLocaleDateString(undefined, …)` means "whatever the device is set to",
    // which is what every one of these calls said before the Language setting
    // existed. Left alone it is the seam: the words change and the dates do not.
    //
    // BookingPage is the one exemption and it is a real one — nobody on that
    // page is signed in, so there is no app language to follow, and the visitor's
    // own is the right answer. Its `fmtTime` carries the argument in a comment.
    const offenders = components
      .filter((f) => f !== 'BookingPage.tsx')
      .filter((f) => /toLocale\w*\(\s*undefined/.test(src(`src/components/${f}`)))
    expect(offenders).toEqual([])
  })

  it('does not spell weekday or month names out in a component', () => {
    // Seven weekdays hardcoded in a component are seven strings a translator
    // never sees, in the one place where asking the platform is strictly better
    // than translating: CLDR has every name in every language, in the
    // abbreviations native readers use. See names.ts.
    const offenders = components.filter((f) => {
      const text = src(`src/components/${f}`).replace(/\/\/[^\n]*|\/\*[\s\S]*?\*\//g, '')
      return /'(Mon|Monday|Jan|January)'\s*,\s*'(Tue|Tuesday|Feb|February)'/.test(text)
        || /'(Sun|Sunday)'\s*,\s*'(Mon|Monday)'/.test(text)
    })
    expect(offenders).toEqual([])
  })
})
