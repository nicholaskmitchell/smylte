// The German grammar, in its own file.
//
// Beside `daytext.test.ts` rather than inside it, because the two suites are
// asking different questions. That one pins the RULES — the position rule, the
// guards, rule 4's refusal to eat the last word — and it does so in English
// because English is where they were worked out. This one pins the WORDS, and
// the handful of places where German's own grammar made a rule decide
// differently.
//
// Everything the two share is asserted once, over there. A case that would read
// the same in either language does not need saying twice, and a suite that said
// it twice would drift.

import { describe, expect, it } from 'vitest'
import { GRAMMARS, parseEntry } from './daytext'
import { de as DE_CATALOGUE } from './i18n/de'
import { en as EN_CATALOGUE } from './i18n/en'

// The same fixed Friday the English suite uses, for the same reason: the module
// promises its reading never depends on the wall clock, and a suite that passed
// `new Date()` could not tell that promise from a coincidence. Friday because it
// is the weekday that makes "Freitag" ambiguous.
const NOW = new Date(2026, 7, 21, 10, 0)

const de = (text: string, now: Date = NOW) => parseEntry(text, now, 'de')

/** The whole shape, for every line that must come back untouched. */
const untouched = (text: string) => ({ summary: text, dueDate: '', dueTime: '', guessed: false })

describe('the language argument', () => {
  it('defaults to English, so nothing that predates it changed', () => {
    // Every caller and every test written before the Language setting passes
    // two arguments. That they still read English is not a nicety — the English
    // suite next door is 116 assertions asserting exactly it.
    expect(parseEntry('gym at 7', NOW)).toEqual(parseEntry('gym at 7', NOW, 'en'))
  })

  it('falls back to English rather than to no grammar at all', () => {
    // The settings blob is hand-editable and `isLanguage` guards the way in,
    // but a box that suddenly read nothing would be a worse failure than a box
    // reading the wrong language, so the lookup has a floor.
    expect(parseEntry('gym at 7', NOW, 'xx' as never))
      .toEqual({ summary: 'gym', dueDate: '', dueTime: '07:00', guessed: true })
  })

  it('is what decides the grammar, not the words in the line', () => {
    // "at 7" is English and reads as English; the same line under the German
    // grammar has no introducer, so the position rule refuses the bare number
    // and the line comes back whole. This is the pair that says the setting is
    // load-bearing rather than decorative.
    expect(de('gym at 7')).toEqual(untouched('gym at 7'))
    expect(de('gym um 7')).toEqual({ summary: 'gym', dueDate: '', dueTime: '07:00', guessed: true })
  })
})

describe('German times', () => {
  it('reads a bare hour when um or @ introduces it', () => {
    expect(de('Sport um 7')).toEqual({ summary: 'Sport', dueDate: '', dueTime: '07:00', guessed: true })
    expect(de('Anruf @ 6')).toEqual({ summary: 'Anruf', dueDate: '', dueTime: '18:00', guessed: true })
  })

  it('takes Uhr as a clock marker, not as a half of the day', () => {
    // "Uhr" plays the colon's part: it says the number is a clock, which
    // satisfies rule 1, and says nothing about morning or evening — so 7 still
    // goes through the inference table and still comes back a guess, while 19
    // states its own half and does not.
    expect(de('Sport 19 Uhr')).toEqual({ summary: 'Sport', dueDate: '', dueTime: '19:00', guessed: false })
    expect(de('Sport 7 Uhr')).toEqual({ summary: 'Sport', dueDate: '', dueTime: '07:00', guessed: true })
    expect(de('Sport um 14 Uhr')).toEqual({ summary: 'Sport', dueDate: '', dueTime: '14:00', guessed: false })
  })

  it('reads the same inference table English does', () => {
    // 1-6 PM, 7-11 AM, 12 noon, 0 and 13-23 as written. Shared on purpose: what
    // "um 3" means is a fact about how people use a clock, not about the word
    // in front of it, and two tables would be two things to keep in step.
    expect(de('Termin um 3').dueTime).toBe('15:00')
    expect(de('Termin um 12').dueTime).toBe('12:00')
    expect(de('Termin um 0:30').dueTime).toBe('00:30')
    expect(de('Termin um 23:15').dueTime).toBe('23:15')
  })

  it('refuses an hour that is not one', () => {
    expect(de('Sport um 25 Uhr')).toEqual(untouched('Sport um 25 Uhr'))
    expect(de('Sport um 7:75')).toEqual(untouched('Sport um 7:75'))
  })

  it('refuses the dotted clock, which is the standard German spelling', () => {
    // Deliberate, and the header says so: 19.30 is also a version number, a
    // decimal and a price, and reading the head of any of those as a clock
    // leaves its tail in the title. "19:30 Uhr" and "um 19:30" both read, and
    // the box's own placeholder teaches the colon.
    expect(de('Sport 19.30 Uhr')).toEqual(untouched('Sport 19.30 Uhr'))
    expect(de('Version 1.30')).toEqual(untouched('Version 1.30'))
    expect(de('Sport 19:30 Uhr')).toEqual({ summary: 'Sport', dueDate: '', dueTime: '19:30', guessed: false })
  })

  it('leaves a bare number alone', () => {
    // Rule 1, in German: "um" is the only introducer, so a number with nothing
    // marking it is never a clock.
    expect(de('Rechnung 1099')).toEqual(untouched('Rechnung 1099'))
    expect(de('kaufe 2 Karten')).toEqual(untouched('kaufe 2 Karten'))
    expect(de('Zimmer 3 buchen')).toEqual(untouched('Zimmer 3 buchen'))
  })

  it('does not read "am" as a meridiem', () => {
    // German has no meridiem, and this is why that matters rather than being a
    // detail: "am" is German's DATE introducer. Admitting it as a meridiem
    // would eat it out of "7 am Montag" — and would refuse "19 am Montag"
    // outright, since 19 with a meridiem is not a time anybody means.
    expect(de('Anruf um 7 am Montag'))
      .toEqual({ summary: 'Anruf', dueDate: '2026-08-24', dueTime: '07:00', guessed: true })
    expect(de('Anruf um 19 am Montag'))
      .toEqual({ summary: 'Anruf', dueDate: '2026-08-24', dueTime: '19:00', guessed: false })
  })

  it('still refuses a dotted English meridiem', () => {
    // The guard is shared rather than per-language: German never writes "p.m.",
    // so it never fires on a German line — but somebody types it anyway, and
    // reading it as 07:00 would be the exact half of the day they ruled out.
    expect(de('Sport um 7 p.m.')).toEqual(untouched('Sport um 7 p.m.'))
  })
})

describe('German dates', () => {
  it('reads a weekday at the end of the line', () => {
    // The line from the box's own placeholder.
    expect(de('Rechnung Freitag'))
      .toEqual({ summary: 'Rechnung', dueDate: '2026-08-28', dueTime: '', guessed: false })
  })

  it('reads am, bis and zum as introducers', () => {
    // "am" locates a day, "bis" states a deadline, "zum" does both — the three
    // the box actually sees, and the analogues of on/at and by.
    expect(de('Meeting am Montag').dueDate).toBe('2026-08-24')
    expect(de('Rechnung bis Freitag').dueDate).toBe('2026-08-28')
    expect(de('Abgabe zum Freitag').dueDate).toBe('2026-08-28')
  })

  it('reads a weekday strictly after today', () => {
    // Typed ON a Friday, a bare "Freitag" means the next one: the day already
    // half spent is the reading the user cannot have meant, since they would
    // have typed "heute".
    expect(de('Sport Freitag').dueDate).toBe('2026-08-28')
  })

  it('reads heute, heute abend and morgen', () => {
    expect(de('Sport heute')).toEqual({ summary: 'Sport', dueDate: '2026-08-21', dueTime: '', guessed: false })
    expect(de('Einkauf morgen')).toEqual({ summary: 'Einkauf', dueDate: '2026-08-22', dueTime: '', guessed: false })
    // "heute abend" carries an hour of its own, exactly as "tonight" does.
    expect(de('Anruf heute abend'))
      .toEqual({ summary: 'Anruf', dueDate: '2026-08-21', dueTime: '19:00', guessed: true })
  })

  it('lets a stated hour beat the one heute abend implies', () => {
    expect(de('Anruf heute abend um 21:00'))
      .toEqual({ summary: 'Anruf', dueDate: '2026-08-21', dueTime: '21:00', guessed: false })
  })

  it('takes nächste* as the week after and kommende*/diese* as this one', () => {
    // German usage is genuinely split on "nächsten Montag" — plenty of speakers
    // mean the one three days away. Following the English rule for `next` is
    // what makes one word mean one thing in both languages, which is worth more
    // than picking a side in somebody else's argument.
    expect(de('Sport nächsten Montag').dueDate).toBe('2026-08-31')
    expect(de('Sport kommenden Montag').dueDate).toBe('2026-08-24')
    expect(de('Sport diesen Montag').dueDate).toBe('2026-08-24')
  })

  it('takes the declined forms, because German declines them', () => {
    for (const mod of ['nächste', 'nächsten', 'nächster', 'nächstes', 'nächstem']) {
      expect(de(`Sport ${mod} Montag`).dueDate).toBe('2026-08-31')
    }
  })

  it('reads Sonnabend as Saturday', () => {
    // Sonntag's neighbour in the north and east. One alternative, and nothing
    // else, to not be wrong for a whole region.
    expect(de('Markt Sonnabend').dueDate).toBe(de('Markt Samstag').dueDate)
  })

  it('refuses a plural, which is a recurrence in disguise', () => {
    expect(de('Sport freitags')).toEqual(untouched('Sport freitags'))
  })

  it('refuses the two-letter abbreviations, deliberately', () => {
    // "so" is an ordinary German word. Admitting Mo/Di/Mi/Do/Fr/Sa/So would
    // import the "enjoy the sun" mangling the English short forms already carry
    // — knowingly, into a second language, where nothing forces it. The cost is
    // a miss, and a miss hands the line back whole.
    expect(de('so machen wir das')).toEqual(untouched('so machen wir das'))
    expect(de('gym am mo')).toEqual(untouched('gym am mo'))
  })

  it('refuses übermorgen, and the reason is JavaScript rather than German', () => {
    // `\b` is defined by ASCII `\w`, so it does not match before `ü` — the
    // anchor that keeps "3friday" out cannot be written for this word, and a day
    // word admitted mid-word is the hole this module exists to not have.
    expect(de('Rechnung übermorgen')).toEqual(untouched('Rechnung übermorgen'))
  })
})

describe('German recurrence', () => {
  it('vetoes a date phrase after jede* or alle', () => {
    // Eating the weekday out of "jeden Montag Sport" is the mangling; the
    // repeat stays legible in the title, where the user can act on it.
    expect(de('jeden Montag Sport')).toEqual(untouched('jeden Montag Sport'))
    expect(de('Sport jede Woche Montag')).toEqual(untouched('Sport jede Woche Montag'))
    expect(de('Sport alle zwei Wochen Montag'))
      .toEqual(untouched('Sport alle zwei Wochen Montag'))
  })

  it('leaves an hour alone, as English does', () => {
    // A bare hour on a recurring line harms nothing: the repeat is still there
    // in the title to be acted on, and the hour is what was asked for.
    expect(de('Sport jeden Montag um 7').dueTime).toBe('07:00')
    expect(de('Sport jeden Montag um 7').dueDate).toBe('')
  })
})

describe('German day ranges', () => {
  it('refuses a range or a list of days', () => {
    // Every candidate in the phrase, not one picked: reading "gym montag bis
    // freitag" as the Friday and handing back "gym montag bis" is exactly the
    // silent loss this module exists to prevent, and the first day of a range
    // is no better an answer than the last.
    expect(de('gym montag bis freitag')).toEqual(untouched('gym montag bis freitag'))
    expect(de('gym samstag und sonntag')).toEqual(untouched('gym samstag und sonntag'))
    expect(de('gym montag-freitag')).toEqual(untouched('gym montag-freitag'))
    expect(de('gym samstag/sonntag')).toEqual(untouched('gym samstag/sonntag'))
    expect(de('gym montag,mittwoch,freitag')).toEqual(untouched('gym montag,mittwoch,freitag'))
  })

  it('still reads a deadline introduced by bis', () => {
    // The German rule is anchored to a day word on the far side of the
    // separator, which the English pair deliberately is not. It has to be: `bis`
    // is also the deadline introducer, and an unanchored rule would refuse
    // "Rechnung bis Freitag" — the single most ordinary line this grammar
    // exists to read.
    expect(de('Rechnung bis Freitag').dueDate).toBe('2026-08-28')
    expect(de('Abgabe bis morgen').dueDate).toBe('2026-08-22')
  })

  it('does not mistake a sentence for a range', () => {
    // The other half of that anchoring, and a case the English grammar gives up
    // on: "und" between a day and a non-day is prose, not a list.
    expect(de('Anruf am Freitag und dann Kaffee').dueDate).toBe('2026-08-28')
  })
})

describe('morgen, which is also a noun', () => {
  // Tomorrow as an adverb, the morning as a noun, and the box is lower-cased
  // prose where the capital that tells them apart cannot be relied on. Reading
  // any of these as tomorrow would date an entry a day out AND eat the word
  // that said so — both halves of a mangling in one line.
  it('refuses am Morgen, which is a time of day', () => {
    expect(de('Meeting am Morgen')).toEqual(untouched('Meeting am Morgen'))
  })

  it('refuses heute Morgen and gestern Morgen, which are already past', () => {
    expect(de('Sport heute Morgen')).toEqual(untouched('Sport heute Morgen'))
    expect(de('Sport gestern Morgen')).toEqual(untouched('Sport gestern Morgen'))
  })

  it('still reads the adverb', () => {
    expect(de('Einkauf morgen').dueDate).toBe('2026-08-22')
    expect(de('Abgabe bis morgen').dueDate).toBe('2026-08-22')
    // Introduced, so the position rule admits it mid-line.
    expect(de('Sport bis morgen früh'))
      .toEqual({ summary: 'Sport früh', dueDate: '2026-08-22', dueTime: '', guessed: false })
  })

  it('is refused mid-line when nothing introduces it, like every day word', () => {
    // Not the noun/adverb problem — the position rule, which is shared and does
    // the same to English: "gym tomorrow early" is refused for the same reason
    // "Sport morgen früh" is. A day word loose in the middle of a sentence is
    // more often a word than a date.
    expect(de('Sport morgen früh')).toEqual(untouched('Sport morgen früh'))
    expect(parseEntry('gym tomorrow early', NOW)).toEqual(untouched('gym tomorrow early'))
  })
})

describe('both phrases in one line', () => {
  it('reads a date and a time together, in either order', () => {
    expect(de('Sport am Freitag um 7'))
      .toEqual({ summary: 'Sport', dueDate: '2026-08-28', dueTime: '07:00', guessed: true })
    expect(de('Sport um 7 am Freitag'))
      .toEqual({ summary: 'Sport', dueDate: '2026-08-28', dueTime: '07:00', guessed: true })
  })

  it('never consumes the only word', () => {
    // Rule 4, in German: an entry dated Friday with no title at all is worse
    // than an untouched line, so the WHOLE reading is abandoned rather than the
    // one phrase that emptied it.
    expect(de('Freitag')).toEqual(untouched('Freitag'))
    expect(de('um 7')).toEqual(untouched('um 7'))
  })
})

describe('the grammars themselves', () => {
  it('give both languages the same guards and the same shape', () => {
    // The rules are about shapes and are shared; only the words differ. A third
    // language added later should have to fill in exactly these fields and
    // nothing else, so this pins the shape rather than any one entry.
    // `veto` is optional — it exists where a language matched something it
    // does not mean, and English has no such word.
    const shape = (g: (typeof GRAMMARS)['en']) =>
      Object.keys(g).filter((k) => k !== 'veto').sort()
    expect(shape(GRAMMARS.de)).toEqual(shape(GRAMMARS.en))
  })

  it('keeps every day pattern global, because the scanners re-enter them', () => {
    // `lastIndex` is reset by hand in both scanners precisely because these are
    // module-level and /g-flagged. A pattern that lost the flag would match once
    // per call and quietly stop finding the second phrase in a line.
    for (const g of Object.values(GRAMMARS)) {
      expect(g.time.flags).toContain('g')
      expect(g.date.flags).toContain('g')
    }
  })
})

describe('the examples the box teaches', () => {
  // An example in a placeholder is a PROMISE that the parser takes that exact
  // text. Nothing else on screen teaches this grammar — there is no help, no
  // syntax note, just the greyed line in the box — so an example that does not
  // parse teaches the wrong thing on the one surface that teaches. de.ts says
  // as much above the entry; this is what makes it true.

  /** The lines quoted inside a placeholder, in either language's quote marks. */
  const examples = (message: string) =>
    [...message.matchAll(/[“„]([^”“]+)[”“]/g)].map((m) => m[1])

  it('reads both German examples in the add box', () => {
    const quoted = examples(DE_CATALOGUE['today.addPlaceholder'] as string)
    expect(quoted).toEqual(['rechnung freitag', 'sport um 7'])
    // A date and a time, one each, exactly as the English pair demonstrates.
    expect(parseEntry(quoted[0], NOW, 'de').dueDate).toBe('2026-08-28')
    expect(parseEntry(quoted[1], NOW, 'de').dueTime).toBe('07:00')
    // And neither is swallowed whole: the title survives, which is the other
    // half of what the example is showing.
    for (const line of quoted) expect(parseEntry(line, NOW, 'de').summary).not.toBe(line)
  })

  it('reads both English examples too, in English', () => {
    // The same promise, kept on the other side, so this guard catches a reword
    // in either catalogue rather than only in the one it was written for.
    const quoted = examples(EN_CATALOGUE['today.addPlaceholder'])
    expect(quoted).toEqual(['invoice friday', 'gym at 7'])
    expect(parseEntry(quoted[0], NOW).dueDate).toBe('2026-08-28')
    expect(parseEntry(quoted[1], NOW).dueTime).toBe('07:00')
  })
})
