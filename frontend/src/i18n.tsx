// The language, and `t`, handed to the leaves that render text.
//
// A context for the reason `TimeFormatProvider` is one, and this is the same
// pattern one step wider: a display-only preference read by nearly every
// component, several of them reachable only through an intermediary with no
// other use for the value. Threading it as a prop would put it in every
// signature between App and a button's label.
//
// The default is English, so a component rendered OUTSIDE the provider — which
// is every existing test — reads exactly the strings it read before. That is
// what makes 500-odd assertions matching on English text keep passing without
// being touched, and it is deliberate rather than lucky: the English catalogue
// holds today's strings verbatim.

import { createContext, Fragment, useContext, useMemo, type ReactNode } from 'react'
import { DEFAULT_LANGUAGE, localeFor, type Language } from './lang'
import { translate, type Vars } from './i18n/index'

export interface I18n {
  lang: Language
  /** The BCP-47 tag for `toLocaleDateString` and friends — see `localeFor`,
   *  which keeps the device's REGION when it agrees with the language. */
  locale: string
  t: (key: string, vars?: Vars) => string
}

function build(lang: Language): I18n {
  return {
    lang,
    locale: localeFor(lang),
    t: (key, vars) => translate(lang, key, vars),
  }
}

const Ctx = createContext<I18n>(build(DEFAULT_LANGUAGE))

export function I18nProvider({ value, children }: { value: Language; children: ReactNode }) {
  // Memoised on the language alone: `t` is an identity several components put
  // in a dependency array, and rebuilding it every render would re-run every
  // memo and effect that names it.
  const i18n = useMemo(() => build(value), [value])
  return <Ctx.Provider value={i18n}>{children}</Ctx.Provider>
}

/** The whole context: `t` for text, `locale` for anything formatted by the
 *  platform, `lang` for the rare caller that switches on it. */
export function useI18n(): I18n {
  return useContext(Ctx)
}

/**
 * Just the translator, for the many components that want nothing else.
 *
 * BOUND AS `tr`, not as `t`, everywhere in this app — `const tr = useT()`. The
 * usual name for this is `t`, and it is taken: `t` is what a dozen components
 * already call the Task or the Tab in a `.map`, and `TasksView` and `TodayView`
 * use it several hundred times between them. One name that never collides beats
 * a convention with an exception list, and a rename of that size in the same
 * commit as a translation layer would bury one in the other.
 */
export function useT(): I18n['t'] {
  return useContext(Ctx).t
}

/**
 * The translator for a sentence with MARKUP inside it.
 *
 * `t` returns a string, which is all most messages need. Some do not: the
 * capacity hint says "Say it as 5h or 300 minutes" with the two examples in the
 * mono face, and the usual way that gets written — three JSX fragments with the
 * spans between them — hands a translator three sentence FRAGMENTS and a fixed
 * order to put them in. That order is a property of English. German moves the
 * verb; a language with a different one cannot be spelled at all.
 *
 * So the message stays one whole sentence with a `{name}` where the marked-up
 * part goes, and the node is dropped in here. The translator moves `{example}`
 * wherever their grammar wants it and the mono face follows it there.
 *
 * String and number vars are still filled in by `translate`, so plural selection
 * and `Intl.NumberFormat` work exactly as they do for `t` — only the node slots
 * are left standing for this to fill.
 */
export function useTx(): (key: string, vars: Record<string, ReactNode>) => ReactNode {
  const { lang } = useI18n()
  return (key, vars) => {
    const scalars: Record<string, string | number> = {}
    for (const [k, v] of Object.entries(vars)) {
      if (typeof v === 'string' || typeof v === 'number') scalars[k] = v
    }
    const text = translate(lang, key, scalars)
    // `split` with a capturing group interleaves the separators, so the odd
    // indices are exactly the placeholder names.
    return text.split(/\{(\w+)\}/g).map((part, i) => (
      // A key is needed because this is an array; the index is stable because
      // the message is, and there is nothing else to key on.
      <Fragment key={i}>{i % 2 ? vars[part] : part}</Fragment>
    ))
  }
}
