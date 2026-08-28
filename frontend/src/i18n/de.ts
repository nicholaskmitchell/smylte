// Deutsch.
//
// ── two decisions that hold across every string below ──────────────────────
//
// DU, NOT SIE. The English copy is direct and personal — "what you wrote about
// each day", "the day you planned it" — and it is written for one owner reading
// their own data on their own server. `Sie` would put a counter between them and
// it. The choice is stated here because it has to be the same in all ~700
// strings, and the first `Ihre` to slip in is the one that makes the rest read
// like a form.
//
// PRODUCT NOUNS STAY GERMAN, PROTOCOL NOUNS STAY AS THEY ARE. Aufgabe, Termin,
// Liste, Kalender are ordinary German words and are used. CalDAV, VTODO, iCal,
// Radicale, Smylte are names — a "VTODO" translated is a "VTODO" nobody can look
// up. Where the English says TRANSP or RRULE, so does this.
//
// Compound nouns are written closed, as German writes them (Kalenderansicht,
// nicht "Kalender Ansicht"), and the leading capital is kept on every noun —
// the two mistakes that make a translated UI read as machine output.

import type { Catalogue } from './index'

export const de: Catalogue = {
  // ── the shell ────────────────────────────────────────────────────────────
  'app.settings': 'Einstellungen',
  'app.retry': 'Erneut versuchen',
  'app.dismiss': 'Schließen',
  'app.back': 'Zurück',
  'app.closeSettings': 'Einstellungen schließen',

  'tab.today': 'Heute',
  'tab.home': 'Start',
  'tab.tasks': 'Aufgaben',
  'tab.calendar': 'Kalender',
  // Not "Terminplanung": this tab is the booking LINKS and what has been booked
  // through them, and "Buchungen" is what the owner would call the list. It also
  // stays clear of "Kalender" next to it, which "Termine" would not.
  'tab.scheduling': 'Buchungen',

  'tabs.opensOn': '\u00D6ffnet mit',
  'tabs.lastUsed': 'Zuletzt genutzter Reiter',
  // Left/right, not up/down, though the buttons are arrows and the list is
  // vertical. The label names what moving does to the STRIP across the top, not
  // what the arrow points at — that is the English's reading and it is not a
  // translator's job to correct it. If it is wrong it is wrong in both
  // languages, which is where a fix belongs.
  'tabs.moveLeft': '{tab} nach links',
  'tabs.moveRight': '{tab} nach rechts',
  'tabs.hint': 'Die Reihenfolge hier ist die Reihenfolge oben. '
    + '\u201EZuletzt genutzter Reiter\u201C \u00F6ffnet dort, wo du aufgeh\u00F6rt hast \u2014 auf '
    + 'jedem Ger\u00E4t, das an diesem Konto angemeldet ist.',

  // ── settings ─────────────────────────────────────────────────────────────
  'settings.sections': 'Einstellungsbereiche',
  'settings.section.general': 'Allgemein',
  'settings.section.appearance': 'Darstellung',
  'settings.section.calendar': 'Kalender',
  'settings.section.tasks': 'Aufgaben',
  'settings.section.account': 'Konto',

  'settings.tabs': 'Reiter',

  'settings.language': 'Sprache',
  'settings.language.aria': 'Sprache, in der die App angezeigt wird',
  'settings.language.hint': 'Die Sprache, in der die App schreibt, und der '
    + 'Kalender, nach dem sie Tage zählt. Deine Listen, Aufgaben und Termine '
    + 'behalten die Namen, die du ihnen gegeben hast.',

  'settings.clock': 'Uhrzeit',
  'settings.clock.aria': '12- oder 24-Stunden-Anzeige',
  'settings.clock.hint': 'Die Uhrzeitanzeige gilt überall dort, wo die App '
    + 'selbst zeichnet. Datums- und Zeitfelder zeichnet der Browser — Chrome, '
    + 'Edge und die Windows-App folgen dieser Einstellung, Firefox folgt '
    + 'deinem System.',
  'clock.12h': '12 Stunden',
  'clock.24h': '24 Stunden',

  'settings.workingDay': 'Arbeitstag',

  'settings.timezone': 'Zeitzone',
  'settings.homeTimezone': 'Eigene Zeitzone',
  'settings.homeTimezone.aria': 'Zeitzone, in der deine Termine geschrieben werden',
  'settings.homeTimezone.title': 'Nach welcher Uhr deine Termine geschrieben '
    + 'werden. Buchungslinks erkennen daran, wann du wirklich belegt bist.',
  'settings.notSet': 'Nicht gesetzt',

  'settings.theme': 'Design',
  'theme.dark': 'Dunkel',
  'theme.light': 'Hell',
  'settings.appearance': 'Darstellung',
  'settings.appearance.customize': 'Anpassen…',
  'settings.appearance.aria': 'Darstellung anpassen',
  'settings.appearance.hint': 'Anpassen öffnet den vollständigen Editor für das '
    + 'Design-System — jeden Farbwert, die Eckenrundung, die Textgröße und die '
    + 'Schriftfamilien — und speichert das Ergebnis als benanntes Design.',

  'settings.calendarWindow': 'Kalenderansicht',
  'settings.calendarFit.aria': 'Festes oder dynamisches Kalenderraster',
  'settings.calendarFit.title': 'Fest hält jede Woche gleich hoch; ein Tag mit '
    + 'mehr Einträgen als hineinpassen wird zu „+N weitere“, statt seine Woche '
    + 'zu dehnen.',
  'settings.calendarFit.hint': 'Eine feste Kalenderansicht bringt den ganzen '
    + 'Monat in den Bereich: jede Woche ist gleich hoch, und ein Tag mit mehr '
    + 'Einträgen als hineinpassen wird zu „+N weitere“. Dynamisch lässt eine '
    + 'volle Woche wachsen und das Raster scrollen.',
  'calendarFit.fixed': 'Fest',
  'calendarFit.dynamic': 'Dynamisch',

  'settings.archivedCalendars': 'Archivierte Kalender',
  'settings.archived.hint': 'Archivieren blendet einen Kalender aus, ohne ihn '
    + 'zu löschen. Listen und Kalender liegen auf dem Radicale-CalDAV-Server — '
    + 'Änderungen dort erscheinen in jedem verbundenen Client, das Archiv aber '
    + 'gehört Smylte allein, und die Sammlung bleibt auf dem Server.',

  'settings.completedTasks': 'Erledigte Aufgaben',
  'settings.completedTasks.shown': 'Sichtbar',
  'settings.completedTasks.hidden': 'Ausgeblendet',
  'settings.completedTasks.hint': 'Ob erledigte Aufgaben in der Hauptansicht '
    + 'bleiben. „Erledigte anzeigen“ in der Seitenleiste funktioniert so oder so.',

  'settings.signedInAs': 'Angemeldet als',
  'settings.staySignedIn': 'Angemeldet bleiben',
  'settings.staySignedIn.aria': 'Wie lange angemeldet bleiben',
  'settings.session.hint': 'Eine kürzere Anmeldung gilt sofort, auf diesem '
    + 'Gerät und auf jedem anderen. Eine längere gilt ab der nächsten Anmeldung.',
  'session.1d': '1 Tag',
  'session.7d': '7 Tage',
  'session.30d': '30 Tage',
  'session.never': 'Nie',
  'settings.connectedApps': 'Verbundene Apps',
  'settings.logout': 'Abmelden',
  // ── archived calendars ──────────────────────────────────────────────────────
  'arch.loading': 'Wird geladen…',
  'arch.loadFailed': 'Deine archivierten Kalender konnten nicht geladen werden.',
  'arch.none': 'Keine archivierten Kalender.',
  'arch.viewEvents': 'Termine ansehen',
  'arch.restore': 'Wiederherstellen',
  'arch.restoreCalendar': 'Kalender wiederherstellen',
  // The English is a range written with an en dash. German writes ranges that
  // way too, but the dates themselves already carry points and spaces, and
  // „5. Feb. – 5. Mrz.“ reads as three separate things. Naming the ends in
  // words says the same fact with less punctuation.
  'arch.showing': 'Termine von {from} bis {to}',
  'arch.calLoadFailed': 'Die Termine dieses Kalenders konnten nicht geladen werden.',
  'arch.noEvents': 'Keine Termine in diesem Zeitraum.',
  'common.allDay': 'ganztägig',
  'common.untitled': '(ohne Titel)',
  // ── connected apps ──────────────────────────────────────────────────────────
  'conn.readWrite': 'Lesen und schreiben',
  'conn.readOnly': 'Nur lesen',
  'conn.noAccess': 'Kein Zugriff',
  'conn.loading': 'Wird geladen…',
  // “not read, not emptied” is the whole point of the sentence: the failure
  // is in the reading, not in the data. German keeps the same contrast.
  'conn.loadFailed': 'Deine verbundenen Anwendungen konnten nicht geladen werden. Erteilte Zugriffe gelten weiter — die Liste ließ sich nicht lesen, sie ist nicht leer.',
  'conn.none': 'Nichts ist verbunden. Anwendungen, die du über den MCP-Endpunkt verbindest, erscheinen hier.',
  'conn.anApplication': 'Eine Anwendung',
  'conn.connectedAt': 'Verbunden {when}',
  'conn.keep': 'Behalten',
  'conn.disconnect': 'Trennen',
  'conn.hint': 'Das Trennen wirkt sofort — die Anwendung muss neu verbunden und erneut freigegeben werden, bevor sie wieder etwas lesen kann.',
  // ── capacity ────────────────────────────────────────────────────────────────
  'capacity.mostDays': 'Meistens',
  'capacity.notSet': 'nicht gesetzt',
  'capacity.defaultDay': 'den üblichen Arbeitstag',
  'capacity.sameAsMostDays': 'wie meistens',
  'capacity.workingTimeFor': 'Arbeitszeit für {name}',
  // {short} and {long} are the two examples in the mono face. They are slots
  // rather than three fragments spliced around <span>s, so this sentence can
  // be reordered — see `useTx` in i18n.tsx.
  'capacity.hint': 'Schreib es als {short} oder {long} Minuten. Ein Tag, dem du keine Länge gegeben hast, wird dir nie angerechnet — der Heute-Tab sagt dann einfach nichts darüber, wie voll er ist.',
  // ── sign in ─────────────────────────────────────────────────────────────────
  'login.invalid': 'Ungültige Zugangsdaten',
  'login.username': 'Benutzername',
  'login.password': 'Passwort',
  'login.submit': 'Anmelden',
  // ── task modal ──────────────────────────────────────────────────────────────
  'taskModal.add': 'Aufgabe hinzufügen',
  'taskModal.edit': 'Aufgabe',
  'common.close': 'Schließen',
  'taskModal.title': 'Titel',
  'taskModal.notes': 'Notizen',
  'taskModal.addMultiple': 'Mehrere hinzufügen',
  'common.delete': 'Löschen',
  'common.add': 'Hinzufügen',
  'common.save': 'Speichern',
}
