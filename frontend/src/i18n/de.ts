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
  'settings.section.notifications': 'Benachrichtigungen',

  // ── Benachrichtigungen ─────────────────────────────────────────────────────
  'notif.intro': 'In Smylte steht ohnehin alles, wonach du später suchen wirst. '
    + 'Eine Benachrichtigung muss also etwas sein, das du nicht nachträglich in '
    + 'der App findest. Darum ist diese Liste kurz.',
  'notif.on': 'An',
  'notif.off': 'Aus',
  'notif.volume.buzzes': 'meldet sich',
  'notif.volume.silent': 'stumm',
  'notif.trigger.aria': 'Benachrichtigung „{rule}“ an- oder ausschalten',
  'notif.trigger.dailyDigest': 'Tagesüberblick',
  'notif.trigger.dailyDigest.hint': 'Die Termine des Tages, was fällig ist und '
    + 'wie viel überfällig — einmal am Morgen. Er ersetzt den Blick in die App, '
    + 'er wirbt nicht für sie.',
  'notif.trigger.eventStarting': 'Vor einem Termin',
  'notif.trigger.eventStarting.hint': 'Das Einzige, was ein Morgenüberblick '
    + 'nicht abdecken kann. Wenn dein Telefonkalender ohnehin erinnert, lass '
    + 'das aus — Smylte sieht diese Alarme nicht und meldet sich sonst doppelt.',
  'notif.trigger.bookingCreated': 'Jemand bucht dich',
  'notif.trigger.bookingCreated.hint': 'Das Einzige in der App, das von außen '
    + 'kommt, während du nicht hinsiehst. Immer stumm: gegen eine Buchung um 3 '
    + 'Uhr lässt sich um 3 Uhr nichts machen.',
  'notif.trigger.syncStalled': 'Sync steht still',
  'notif.trigger.syncStalled.hint': 'Der eine Zustand, in dem die App dich '
    + 'täuscht — alles sieht normal aus und die Daten sind eingefroren. Höchstens '
    + 'eine stumme Nachricht am Tag, mit dem Namen der Liste statt der '
    + 'Fehlermeldung.',
  'notif.timing': 'Zeitpunkt',
  'notif.digestTime': 'Überblick kommt um',
  'notif.digestTime.hint': 'In deiner Heimatzeitzone ({tz}). Ein Überblick, der '
    + 'mehr als vier Stunden zu spät wäre, entfällt — er würde einen Morgen '
    + 'beschreiben, der schon vorbei ist.',
  'notif.digestTime.noTz': 'Stelle zuerst unter Allgemein eine Heimatzeitzone '
    + 'ein. Ohne sie kommt der Überblick gar nicht: eine Uhrzeit, die gegen die '
    + 'Serveruhr aufgelöst wird, ist nicht die Uhrzeit, die du gewählt hast.',
  'notif.eventLead': 'Vorlauf vor Terminen',
  'notif.eventLead.hint': 'Minuten Vorwarnung, bevor ein Termin beginnt. Drei '
    + 'ist das Minimum: Abgleich und Prüfung kosten zusammen fast zwei Minuten, '
    + 'und eine Meldung nach Terminbeginn wird nie verschickt.',
  'notif.ceiling.hint': 'Ab acht hörbaren Nachrichten am Tag kommen die '
    + 'übrigen stumm an. Verworfen wird nie etwas — ein Kanal, der bei allem '
    + 'summt, wird stummgeschaltet, und dann sagt er dir auch nicht mehr, dass '
    + 'der Termin in zehn Minuten beginnt.',
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
  // ── plan ritual ─────────────────────────────────────────────────────────────
  'plan.step.capacity': 'Wie lang ist heute?',
  'plan.step.pick': 'Was machst du heute?',
  'plan.step.shape': 'In Form bringen',
  'plan.aria': 'Plane deinen Tag',
  'plan.stepOf': '{n} von {total}',
  'plan.total': '{planned} von {capacity}',
  // Keeps the leading separator, because the three fragments of this line are
  // concatenated in the component and the middle one has to bring its own.
  'plan.unestimated': ' · {count} ohne Schätzung',
  'plan.over': ' · {amount} zu viel',
  'common.back': 'Zurück',
  'plan.skip': 'Überspringen',
  'plan.done': 'Fertig',
  'plan.start': 'Tag beginnen',
  'plan.next': 'Weiter',
  'plan.warn': 'Das ist {amount} mehr, als du arbeiten wolltest. Du kannst trotzdem anfangen — aber jetzt etwas zu verschieben ist leichter als um vier.',
  'plan.stopping': 'Wann hörst du heute auf?',
  // The examples must be things the parser actually takes, so these change
  // when daytext.ts learns German and not before. See daytext.ts.
  'plan.capacityPlaceholder': 'bis 18 Uhr, oder 5h',
  'plan.capacityAria': 'Wie lange du heute arbeitest',
  'plan.capacityRefused': 'Versuch {a} oder {b}.',
  'plan.capacityHint': 'Beides geht — {a} oder {b}. Das gilt nur für heute; in den Einstellungen steht die Vorgabe.',
  'plan.meetings': 'Du hast heute schon {amount} im Kalender.',
  'plan.leftovers': 'Das ist letztes Mal liegen geblieben',
  'plan.nothingWaiting': 'Nichts liegt an. Was heute sonst noch ansteht, tippst du in das Feld dahinter.',
  'plan.addToToday': '{task} zu heute hinzufügen',
  'common.task': 'Aufgabe',
  'plan.nothingOnToday': 'Heute steht noch nichts an.',
  'plan.shapeHint': 'Tippe auf eine Schätzung, um sie zu setzen. Zieh eine Zeile, um sie zu verschieben.',
  // ── parser examples ─────────────────────────────────────────────────────────
  // An example is a PROMISE that the parser takes this exact text. Its German
  // is therefore not a translator's choice but a fact about `parseCapacity`,
  // and the two have to change together — see daytext.ts.
  'capacity.example.until': 'bis 18 Uhr',
  'capacity.example.length': '5h',
  // ── shutdown ritual ─────────────────────────────────────────────────────────
  'shut.step.done': 'Wie heute lief',
  'shut.step.follows': 'Was dir folgt',
  'shut.step.reflect': 'Etwas festzuhalten?',
  'shut.aria': 'Den Tag abschließen',
  'shut.done': 'Fertig',
  'shut.shutDown': 'Abschließen',
  'shut.alreadyShutdown': 'Du hast heute um {time} abgeschlossen. Was du von hier aus änderst, landet trotzdem auf heute.',
  'shut.doneCount': '{done} von {total} erledigt',
  'shut.plannedOf': ' · {done} von {planned} geplant',
  'shut.unestimated': ' · {count} ohne Schätzung',
  'shut.offPlan': 'Ungeplant erledigt',
  'shut.doneMark': 'Erledigt',
  'shut.nothingAtAll': 'Nichts auf heute, und ungeplant auch nichts erledigt.',
  'shut.allDecided': 'Über alles von heute ist entschieden. Es bleibt nichts übrig.',
  'shut.allDone': 'Alles von heute ist erledigt. Es bleibt nichts übrig.',
  'shut.followsHint': 'Was du in Ruhe lässt, wandert von selbst weiter — hier geht es um die Zeilen, über die du entscheiden willst. Eine Entscheidung nimmt die Zeile aus dieser Liste.',
  'shut.moveAll': 'Alle {count} auf morgen schieben',
  'shut.thisTask': '(diese Aufgabe)',
  'shut.moveToTomorrow': '{task} auf morgen schieben',
  'shut.tomorrow': 'Morgen',
  'shut.moveToDay': '{task} auf einen Tag schieben',
  'shut.takeOff': '{task} aus dem Plan nehmen',
  'shut.offThePlan': 'Nicht im Plan',
  'shut.howDidItGo': 'Wie war dein Tag?',
  'shut.reflectPlaceholder': 'Ein Satz reicht völlig.',
  'shut.reflectAria': 'Eine Notiz zu heute',
  'shut.reflectHint': 'Bleibt beim Tag. Du siehst sie jedes Mal, wenn du auf heute zurückschaust.',
  // ── task fields ─────────────────────────────────────────────────────────────
  'field.list': 'Liste',
  'field.due': 'Fällig',
  'field.dueDate': 'Fälligkeitsdatum',
  'field.dueTime': 'Fälligkeitszeit',
  'field.start': 'Beginn',
  'field.startDate': 'Startdatum',
  'field.startTime': 'Startzeit',
  'field.priority': 'Priorität',
  'field.tags': 'Schlagwörter',
  'field.notes': 'Notizen',
  // A SUFFIX in English and a suffix in German, but written as a whole
  // message with the field name in a slot — a language that puts the scope
  // in front can say so, and this file cannot tell it not to.
  'field.forAll': '{name}, für alle Aufgaben',
  'field.forRow': '{name}, Zeile {n}',
  'tags.remove': '{tag} entfernen',
  'tags.placeholder': 'Schlagwort hinzufügen…',
  // ── add multiple ────────────────────────────────────────────────────────────
  'bulk.aria': 'Mehrere Aufgaben hinzufügen',
  'bulk.title': 'Mehrere hinzufügen',
  'bulk.sameForAll': 'Für alle gleich',
  'bulk.rowTitle': 'Titel',
  'bulk.titleForRow': 'Titel, Zeile {n}',
  'bulk.titlePlaceholder': 'Aufgabentitel',
  'bulk.removeRow': 'Zeile {n} entfernen',
  'bulk.addRow': 'Noch eine Zeile',
  'bulk.addRowShort': '+ Zeile',
  'bulk.truncated': 'Nur die ersten {max} Zeilen wurden übernommen.',
  'bulk.pasteHint': 'Füg eine Liste von Titeln ein, um mehrere Zeilen auf einmal zu füllen.',
  // One message, not a fragment plus "— press Add to retry." concatenated
  // after it: the English put the singular/plural half in a ternary and the
  // tail outside it, which hands a translator two pieces and an order.
  //
  // "Die Zeile", not "Ihre Zeile". The possessive would be correct German —
  // ihre, the task's — but it lands first in the sentence and so is capitalised,
  // and a capital Ihre is indistinguishable from the formal address this app
  // does not use. The du/Sie guard cannot tell them apart and should not try:
  // the case it would have to allow through is exactly the one worth catching.
  'bulk.failed': {
    one: '1 Aufgabe konnte nicht angelegt werden. Die Zeile ist geblieben — drück auf Hinzufügen, um es noch einmal zu versuchen.',
    other: '{count} Aufgaben konnten nicht angelegt werden. Die Zeilen sind geblieben — drück auf Hinzufügen, um es noch einmal zu versuchen.',
  },
  'bulk.progress': '{done} / {total}',
  'bulk.adding': 'Wird hinzugefügt…',
  // German puts the count first and the verb last, which is exactly the
  // reordering a ternary on `n === 1` around a fixed "Add " prefix cannot
  // express.
  'bulk.submit': {
    one: '{count} Aufgabe hinzufügen',
    other: '{count} Aufgaben hinzufügen',
  },
  'bulk.submitEmpty': 'Aufgaben hinzufügen',
  // ── home / dashboard ────────────────────────────────────────────────────────
  'module.today': 'Heute',
  'module.today.blurb': 'Aufgaben, die heute fällig sind — über alle Listen.',
  'module.overdue': 'Überfällig',
  'module.overdue.blurb': 'Alles, dessen Fälligkeit vorbei ist.',
  'module.upcoming': 'Demnächst',
  'module.upcoming.blurb': 'Die Aufgaben der nächsten sieben Tage.',
  'module.mini_calendar': 'Minikalender',
  'module.mini_calendar.blurb': 'Dieser Monat, gepunktet in der Farbe jedes Kalenders.',
  'module.completed': 'Zuletzt erledigt',
  'module.completed.blurb': 'Was du zuletzt fertig bekommen hast.',
  'module.booking_links': 'Buchungslinks',
  'module.booking_links.blurb': 'Deine Buchungslinks und ihr Zustand.',
  'module.bookings': 'Anstehende Buchungen',
  'module.bookings.blurb': 'Wer Zeit bei dir gebucht hat.',
  'module.quick_add': 'Schnell hinzufügen',
  'module.quick_add.blurb': 'Eine Aufgabe direkt auf eine Liste werfen.',
  'home.title': 'Start',
  'home.moduleCount': '{count} Module',
  'home.arrangeHint': 'Ziehen zum Verschieben · Ecke zum Skalieren',
  'home.addModule': 'Modul hinzufügen',
  'home.resetLayout': 'Layout zurücksetzen',
  'home.arrangeDone': 'Fertig',
  'home.arrange': 'Anordnen',
  'home.picker': 'Ein Modul hinzufügen',
  'common.remove': 'Entfernen',
  'home.removeModule': '{module} entfernen',
  'home.emptyToday': 'Heute ist nichts fällig.',
  'home.emptyOverdue': 'Nichts überfällig.',
  'home.emptyUpcoming': 'Nichts in den nächsten sieben Tagen.',
  'home.emptyCompleted': 'Noch nichts erledigt.',
  'home.calPartial': '{cals} konnte nicht geladen werden — es fehlen vielleicht Termine.',
  'home.dayWithEvents': {
    one: '{day}, {count} Termin',
    other: '{day}, {count} Termine',
  },
  'home.noLinks': 'Noch keine Buchungslinks.',
  // The unit stays "m", untranslated, to match `fmtDuration` — which is
  // React-free and language-neutral on purpose (see time.ts). "30 Min." here
  // and "30m" on every estimate would be two spellings of one unit on one
  // screen.
  'home.linkDuration': '{n}m',
  'home.noBookings': 'Keine anstehenden Buchungen.',
  'home.needList': 'Leg zuerst eine Liste an.',
  'home.quickAddPlaceholder': 'Aufgabe hinzufügen…',
  'home.quickAddAria': 'Aufgabe hinzufügen',
  'home.addedTo': 'Zu {list} hinzugefügt.',
  // ── sidebar — the collection words ──────────────────────────────────────────
  'side.lists.heading': 'Listen',
  'side.lists.one': 'Liste',
  'side.lists.new': 'Neue Liste',
  'side.lists.manage': 'Listen verwalten',
  'side.lists.groupEmpty': 'Leer — ordne eine Liste über ihr ⋯-Menü zu',
  'side.lists.dropHere': 'Zieh eine Liste hierher',
  'side.lists.tapHint': 'Tipp auf eine Liste, um sie ein- oder auszublenden. Tipp auf ⋯ zum Umbenennen, Umfärben{archive} oder Löschen.',
  'side.calendars.heading': 'Kalender',
  'side.calendars.one': 'Kalender',
  'side.calendars.new': 'Neuer Kalender',
  'side.calendars.manage': 'Kalender verwalten',
  'side.calendars.groupEmpty': 'Leer — ordne einen Kalender über sein ⋯-Menü zu',
  'side.calendars.dropHere': 'Zieh einen Kalender hierher',
  'side.calendars.tapHint': 'Tipp auf einen Kalender, um ihn ein- oder auszublenden. Tipp auf ⋯ zum Umbenennen, Umfärben{archive} oder Löschen.',
  'side.archiveClause': ', Archivieren',
  // ── sidebar ─────────────────────────────────────────────────────────────────
  'side.edit': 'Bearbeiten',
  'side.editItem': '{name} bearbeiten',
  'side.nothingHere': 'Hier ist noch nichts.',
  'side.groupName': 'Gruppenname',
  'side.backToTasks': '← Zurück zu den Aufgaben',
  'side.viewCompleted': '✓ Erledigte anzeigen',
  'side.backToTasksShort': 'Zurück zu den Aufgaben',
  'side.viewCompletedShort': 'Erledigte anzeigen',
  'side.noneYet': 'Noch keine',
  'side.shownOf': '{shown} von {total} sichtbar',
  'side.newGroup': 'Neue Gruppe',
  'side.drawerDone': 'Fertig',
  'side.expand': 'Seitenleiste ausklappen',
  'side.collapse': 'Seitenleiste einklappen',
  'side.groupExpand': 'Ausklappen',
  'side.groupCollapse': 'Einklappen',
  'side.hideAllInGroup': 'Alle in der Gruppe ausblenden',
  'side.showAllInGroup': 'Alle in der Gruppe einblenden',
  'side.deleteGroupTitle': 'Gruppe löschen (Listen bleiben)',
  'side.deleteGroupConfirmAria': 'löschen? — Gruppe {name}, Listen bleiben',
  'side.deleteGroupConfirm': 'löschen?',
  'side.keepGroup': 'Gruppe behalten',
  'common.cancel': 'Abbrechen',
  'side.renameGroup': 'Gruppe umbenennen',
  'side.renameGroupOf': 'Gruppe {name} umbenennen',
  'side.deleteGroup': 'Gruppe löschen',
  'side.deleteGroupOf': 'Gruppe {name} löschen',
  'side.noColor': 'Keine Farbe',
  'side.customColor': 'Eigene Farbe',
  'side.name': 'Name',
  'side.color': 'Farbe',
  'side.group': 'Gruppe',
  'side.noGroup': 'Keine Gruppe',
  'side.reallyDelete': 'Wirklich löschen?',
  'side.archiveTitle': 'Ausblenden statt löschen — später in den Einstellungen wiederherstellbar',
  'side.archive': 'Archivieren',
  // ── tasks tab ───────────────────────────────────────────────────────────────
  'tasks.view.list': 'Liste',
  'tasks.view.day3': '3 Tage',
  'tasks.view.week': 'Woche',
  'tasks.completed': 'Erledigt',
  'tasks.allLists': 'Alle Listen',
  'tasks.completedCount': '{count} erledigt',
  'tasks.openCount': '{count} offen',
  'tasks.range': '{from} – {to}',
  'tasks.earlier': 'Früher',
  'tasks.later': 'Später',
  'tasks.today': 'Heute',
  'tasks.viewTabs': 'Aufgabenansicht',
  'tasks.noCompleted': 'Keine erledigten Aufgaben.',
  'common.loading': 'Wird geladen…',
  'tasks.createListFirst': 'Leg eine Liste an, um loszulegen.',
  'tasks.allHidden': 'Alle Listen sind ausgeblendet — schalte in der Seitenleiste eine ein.',
  'tasks.partial': '{lists} konnte nicht geladen werden — es fehlen vielleicht Aufgaben.',
  'common.retry': 'Erneut versuchen',
  'tasks.nothingToDo': 'Hier gibt es nichts zu tun.',
  'tasks.completedSection': 'Erledigt · {count}',
  // Keeps its trailing dash and space: the button that finishes the sentence
  // follows it in the markup, and only the sentence can say where the break
  // goes.
  'tasks.undatedHidden': {
    one: '{count} Aufgabe ohne Datum wird nicht gezeigt — ',
    other: '{count} Aufgaben ohne Datum werden nicht gezeigt — ',
  },
  'tasks.switchToList': 'zur Liste wechseln',
  'tasks.overdueHidden': {
    one: '{count} überfällige Aufgabe wird nicht gezeigt — ',
    other: '{count} überfällige Aufgaben werden nicht gezeigt — ',
  },
  'tasks.jumpToToday': 'zu heute springen',
  'tasks.overdue': 'Überfällig',
  'tasks.doneSection': 'Erledigt · {count}',
  'tasks.colAdd': '+ Neu',
  'tasks.toggleComplete': 'Erledigt umschalten',
  'tasks.showSubtasks': 'Unteraufgaben von {task} zeigen',
  'tasks.hideSubtasks': 'Unteraufgaben von {task} verbergen',
  'tasks.wontDo': 'wird nichts',
  'tasks.addSubtask': 'Unteraufgabe hinzufügen',
  'tasks.addSubtaskShort': '+ Unter',
  'tasks.deleteShort': 'lösch',
  'tasks.quickAddPlaceholder': 'Aufgabe hinzufügen…',
  'tasks.quickAddList': 'Liste für die neue Aufgabe',
  'tasks.openFullForm': 'Das ganze Formular für eine neue Aufgabe öffnen',
  'tasks.newEllipsis': 'Neu…',
  'tasks.subtaskPlaceholder': 'Unteraufgabe',
  // ── calendar tab ────────────────────────────────────────────────────────────
  'cal.showTaskLists': 'Aufgabenlisten zeigen',
  'cal.hideTaskLists': 'Aufgabenlisten verbergen',
  'cal.tasksGroup': 'Aufgaben',
  'cal.takeTasksOff': 'Aufgabenlisten vom Kalender nehmen',
  'cal.putTasksOn': 'Jede Aufgabenliste auf den Kalender legen',
  'cal.completedShown': 'Erledigte · sichtbar',
  'cal.completedHidden': 'Erledigte · verborgen',
  'cal.createCalendarFirst': 'Leg einen Kalender an, um loszulegen.',
  'cal.allArchived': 'Alle Kalender sind archiviert — stell in den Einstellungen einen wieder her.',
  'cal.partial': '{cals} konnte nicht geladen werden — in diesem Monat fehlen vielleicht Termine.',
  'cal.grid': 'Monat',
  'cal.newEvent': 'Neuer Termin',
  'cal.repeatingTitle': '{summary} (wiederkehrend)',
  'cal.dragEndDay': 'Ziehen, um den letzten Tag zu ändern',
  'cal.moreOnDay': '+{count} weitere',
  'cal.addEvent': '+ Termin',
  'cal.nothingThisDay': 'An diesem Tag nichts.',
  'cal.repeatingEvent': 'Wiederkehrender Termin',
  'cal.event': 'Termin',
  'cal.applyToWhich': 'Auf welche Termine soll die Änderung wirken?',
  'cal.applyChangesToWhich': 'Auf welche Termine sollen die Änderungen wirken?',
  'cal.deleteWhich': 'Welche Termine sollen gelöscht werden?',
  'cal.scope.this': 'Diesen Termin',
  'cal.scope.following': 'Diesen und die folgenden',
  'cal.scope.all': 'Alle Termine',
  'cal.cadenceBlocked': 'Die geänderte Wiederholung braucht „Diesen und die folgenden“ oder „Alle Termine“ — ein einzelner Termin hat keinen eigenen Rhythmus.',
  // The quoted names here are BUTTON labels and a select option. If any of
  // them is reworded, this sentence stops pointing at anything: cal.scope.*
  // and cal.repeat.keep are the three it names.
  'cal.cadenceRefused': 'Eine geänderte Wiederholung kann nicht für einen einzelnen Termin gelten. Nimm „Diesen und die folgenden“ oder „Alle Termine“, oder stell Wiederholung zurück auf „Rhythmus beibehalten“.',
  'cal.title': 'Titel',
  'cal.startField': 'Beginn',
  'cal.endLastDay': 'Ende (letzter Tag)',
  'cal.end': 'Ende',
  'cal.repeat': 'Wiederholung',
  'cal.repeat.keep': 'Rhythmus beibehalten',
  'cal.repeat.none': 'Wiederholt sich nicht',
  'cal.repeat.daily': 'Täglich',
  'cal.repeat.weekly': 'Wöchentlich',
  'cal.repeat.monthly': 'Monatlich',
  'cal.repeat.yearly': 'Jährlich',
  'cal.showAs': 'Anzeigen als',
  // Apple's German calendar says „Gebucht“ and „Frei“ for TRANSP, and this
  // is the same field — an owner who set Busy in Apple should meet the same
  // word here. Not „Beschäftigt“, which is about the person rather than the
  // time.
  'cal.busy': 'Gebucht',
  'cal.free': 'Frei',
  'cal.freeHint': 'Freie Zeit kann trotzdem gebucht werden — das blockiert keinen Termin auf deinen Buchungslinks.',
  'cal.repeatUntil': 'Wiederholen bis (optional)',
  'cal.calendarField': 'Kalender',
  'cal.location': 'Ort',
  'cal.notes': 'Notizen',
  'cal.moveHint': '„Alle Termine“ verschiebt jeden Termin um denselben Abstand — nimm „Diesen Termin“, um nur einen zu verschieben.',
  // ── scheduling tab ──────────────────────────────────────────────────────────
  'sched.title': 'Buchungen',
  'sched.newLink': 'Neuer Link',
  'sched.loadFailed': 'Deine Buchungslinks konnten nicht geladen werden. Das ist ein Anzeigeproblem — die Links sind weiter aktiv und nehmen weiter Buchungen an.',
  'sched.empty': 'Leg einen Buchungslink an, gib ihn an jemanden weiter, und was die Person wählt, landet in deinem Kalender.',
  'sched.calendarGone': 'Der Kalender, in den dieser Link bucht, existiert nicht mehr',
  'sched.linkLive': 'Link ist aktiv',
  'sched.linkOff': 'Link ist aus',
  'sched.noCalendar': 'Kein Kalender',
  'sched.live': 'Aktiv',
  'sched.off': 'Aus',
  'sched.minutes': '{n} Min.',
  'sched.calendarDeleted': 'Kalender gelöscht — wähl einen anderen, um ihn wieder zu aktivieren',
  'sched.showsBusy': ' · zeigt gebuchte Zeiten',
  'sched.bookingCount': {
    one: '{count} Buchung',
    other: '{count} Buchungen',
  },
  'sched.copied': 'Kopiert ✓',
  'sched.copyLink': 'Link kopieren',
  'common.edit': 'Bearbeiten',
  'sched.upcoming': 'Anstehende Buchungen',
  'sched.nothingBooked': 'Noch nichts gebucht.',
  'sched.err.title': 'Gib dem Link einen Titel.',
  'sched.err.calendar': 'Wähl einen Kalender, in dem die Buchungen landen.',
  'sched.err.tz': 'Leg fest, in welcher Zeitzone deine Verfügbarkeit gilt.',
  'sched.err.noDays': 'Schalte mindestens einen Tag ein, sonst kann niemand etwas buchen.',
  'sched.err.ranges': 'Korrigier die hervorgehobenen Zeitspannen.',
  'sched.err.bothTimes': 'Füll beide Zeiten aus, oder entfern die Spanne.',
  'sched.err.startBeforeEnd': 'Jede Spanne muss vor ihrem Ende beginnen.',
  'sched.err.overlap': 'Diese Spannen überschneiden sich.',
  'sched.editLink': 'Buchungslink bearbeiten',
  'sched.newLinkTitle': 'Neuer Buchungslink',
  'sched.titleField': 'Titel',
  'sched.titlePlaceholder': '30-minütiges Kennenlernen',
  'sched.description': 'Beschreibung (für die Gäste sichtbar)',
  'sched.calendarField': 'Kalender',
  'sched.duration': 'Dauer (Min.)',
  'sched.timezone': 'Zeitzone (deine Verfügbarkeit gilt in dieser Zone)',
  'sched.weekly': 'Wöchentliche Verfügbarkeit',
  'sched.removeRange': 'Spanne entfernen',
  'sched.addRange': 'Noch eine Spanne',
  'sched.addRangeShort': '+ Spanne',
  'sched.unavailable': 'Nicht verfügbar',
  'sched.showBusy': 'Meine gebuchten Zeiten auf der Buchungsseite zeigen',
  // „Gebucht“ here is the same word as cal.busy, on purpose: this sentence
  // describes what a visitor sees on the booking page, and that block is
  // labelled from the same idea.
  'sched.showBusyHint': 'Gäste sehen nur unbeschriftete Blöcke „Gebucht“ — nie Titel oder Details. Gebuchte und bestehende Termine mit Uhrzeit blockieren immer; ganztägige Termine (Geburtstage, Reisen) nicht.',
  'sched.buffer': 'Puffer (Min.)',
  'sched.notice': 'Mindestvorlauf (Std.)',
  'sched.horizon': 'Tage im Voraus',
  'sched.createLink': 'Link anlegen',
  // ── today tab ───────────────────────────────────────────────────────────────
  'today.group.chosen': 'Ausgewählt',
  'today.group.carried': 'Übernommen',
  'today.group.derived': 'Abgeleitet',
  'today.group.habits': 'Gewohnheiten',
  'today.group.other': 'Sonstiges',
  'today.group.moved': 'Weitergeschoben',
  'today.group.dropped': 'Fallengelassen',
  'today.kind.task': 'Aufgabe',
  'today.kind.note': 'Notiz',
  'today.kind.habit': 'Gewohnheit',
  'today.kind.entry': 'Eintrag',
  'today.taskGone': 'Diese Aufgabe steht in keiner deiner Listen mehr',
  'today.sug.today': 'Heute fällig',
  'today.sug.overdue': 'Überfällig',
  'today.sug.soon': 'Nächste sieben Tage',
  'today.sug.open': 'Aus einem letzten Plan noch offen',
  'today.sug.stale': 'Seit {days} Tagen unangetastet',
  'today.title': 'Heute',
  'today.lookBack': 'Rückblick',
  'today.prevDay': 'Vorheriger Tag',
  'today.nextDay': 'Nächster Tag',
  'today.countOpen': '{open} offen · {total} am Tag',
  'today.countDone': '{done} erledigt · {total} am Tag',
  'today.modePlan': 'Planen',
  'today.modeReview': 'Rückblick',
  'today.shutDown': 'Abschließen',
  'today.habits': 'Gewohnheiten',
  'today.addAria': 'Zu heute hinzufügen',
  // Both examples are lines the PARSER has to read. They change with
  // daytext.ts's German grammar and not before it — an example that does not
  // parse teaches the wrong thing on the one surface that teaches.
  'today.addPlaceholder': 'Zu heute hinzufügen — „rechnung freitag“, „sport um 7“…',
  'today.addAsTask': 'Als Aufgabe hinzufügen',
  'today.addAsNote': 'Als Notiz hinzufügen',
  'today.willAdd': 'fügt hinzu',
  'today.guess': ' (geraten)',
  'today.fate.note': 'nur an diesem Tag — es verlässt Smylte nie',
  'today.fate.taskAnyList': 'es taucht auch in deinen anderen Apps auf',
  'today.fate.taskNamedList': 'auf {list} — es taucht auch in deinen anderen Apps auf',
  'today.yourLists': 'deinen Listen',
  'today.makeItNote': 'Als Notiz',
  'today.makeItTask': 'Als Aufgabe',
  'today.listForNewTask': 'Liste für die neue Aufgabe',
  'today.bandNoCapacity': 'Plan deinen Tag — sag, wie lang er ist, dann was darauf soll.',
  'today.bandCapacity': 'Plan deinen Tag — {capacity} stehen zur Verfügung.',
  'today.planMyDay': 'Tag planen',
  'today.notNow': 'Jetzt nicht',
  'today.loadFigure': '{planned} von {capacity}',
  'today.loadCalendar': ' · {amount} im Kalender',
  'today.loadUnestimated': ' · {count} ohne Schätzung',
  'today.over': 'Das ist {amount} mehr, als du arbeiten wolltest.',
  'today.readFailed': 'Heute konnte nicht gelesen werden.',
  'today.tryAgain': 'Nochmal versuchen',
  // Split around the “set up a habit” button that finishes the sentence.
  // The trailing space and the closing period are part of the two halves,
  // so a translator controls where the break falls.
  'today.emptyBefore': 'Heute steht noch nichts an. Tipp oben eine Zeile, nimm eine der Aufgaben von unten, oder ',
  'today.setUpHabit': 'richte eine Gewohnheit ein',
  // Both habit blurbs run the second clause on with an em dash rather than
  // starting a new sentence with the pronoun. „Sie wird nie zur Aufgabe“ is
  // correct German — sie, the Gewohnheit — but sentence-initial it capitalises
  // to Sie, which the du/Sie guard cannot tell from the formal address, and
  // should not have to. See bulk.failed for the same call.
  'today.habitsHint': 'Eine Gewohnheit ist eine Regel, die an den Tagen, die du wählst, eine Zeile auf deinen Tag setzt — und dabei nie zur Aufgabe wird und diese App nie verlässt. ',
  'today.setOneUp': 'Richte eine ein',
  'today.theDay': 'Der Tag',
  'today.onTheCalendar': 'Im Kalender',
  'today.addToToday': '{task} zu heute hinzufügen',
  'today.showAll': 'Alle {count} zeigen',
  'today.howItWent': 'Wie es lief',
  'today.doneOffPlan': 'Ungeplant erledigt',
  'today.doneMark': 'Erledigt',
  'today.reviewEmptyLive': 'Heute steht noch nichts an, und erledigt ist bisher auch nichts.',
  'today.reviewEmptyPast': 'An diesem Tag war nichts geplant, und erledigt wurde auch nichts.',
  'today.noCalendar': 'Heute steht nichts im Kalender.',
  'today.estimateAria': '{entry} schätzen',
  'today.estimatedAt': '{entry} ist auf {amount} geschätzt — ändern',
  'today.est': 'schätz',
  'today.minutesFor': 'Minuten für {entry}',
  'today.thisEntry': 'dieser Eintrag',
  'today.entry': 'Eintrag',
  'today.uncheck': '{entry} abhaken rückgängig',
  'today.check': '{entry} abhaken',
  'today.weekCountThis': '{done} von {total} diese Woche',
  'today.weekCountThat': '{done} von {total} in jener Woche bis dahin',
  'today.movedTo': '→ {day}',
  'today.removeFromToday': '{entry} von heute entfernen',
  'habit.sheet.blurb': 'Eine Gewohnheit ist eine Regel, die eine Zeile auf deinen Tag setzt — und dabei nie zur Aufgabe wird und diese App nie verlässt.',
  'habit.none': 'Noch keine Gewohnheiten.',
  'habit.newAria': 'Neue Gewohnheit',
  'habit.addPlaceholder': 'Gewohnheit hinzufügen — „lesen“, „dehnen“…',
  'habit.rename': '{habit} umbenennen',
  'habit.resumeAria': '{habit} fortsetzen',
  'habit.pauseAria': '{habit} pausieren',
  'habit.resume': 'Fortsetzen',
  'habit.pause': 'Pausieren',
  'habit.confirmDelete': 'Löschen von {habit} bestätigen',
  'habit.delete': '{habit} löschen',
  'habit.dayFor': '{day} für {habit}',
  'habit.everyDay': 'Jeden Tag',
  'habit.paused': 'Pausiert',
  'habit.deleteWarn': 'Die Regel kommt nicht mehr wieder. Jeder Tag, an dem sie schon lief, behält die Zeile, die sie dort gesetzt hat — ein vergangener Tag ist ein abgeschlossener Bericht, keine Hochrechnung der heutigen Regeln.',
  // ── the shell's own messages ────────────────────────────────────────────────
  'app.settingsLoadFailed': 'Deine Einstellungen konnten nicht geladen werden — Änderungen werden erst gespeichert, wenn das hier neu lädt',
  'app.settingsNotLoaded': 'Deine Einstellungen wurden nicht geladen, also ist diese Änderung nicht gespeichert — lad neu, um es noch einmal zu versuchen',
  // {error} arrives from the server in English and stays that way — see the
  // header of i18n/index.ts on why server text is out of scope. The sentence
  // around it is still worth having in the reader's language.
  'app.settingsSaveFailed': 'Deine Einstellungen konnten nicht gespeichert werden: {error}',
  'app.logoutFailed': 'Abmelden hat nicht geklappt — du bist auf diesem Gerät weiter angemeldet.',
  'app.offline': 'Der Server ist nicht erreichbar — gezeigt wird, was zuletzt auf diesem Gerät gespeichert wurde. Du bist weiter angemeldet.',
  // ── appearance — design tokens ──────────────────────────────────────────────
  'token.bg': 'Hintergrund',
  'token.bgElev': 'Erhöht',
  'token.bgElev.hint': 'Karten, Dialoge, Hover-Zustände.',
  'token.paper': 'Vertieft',
  'token.paper.hint': 'Seitenleiste und Spaltenköpfe.',
  'token.fg': 'Text',
  'token.fgMuted': 'Gedämpft',
  'token.fgFaint': 'Blass',
  'token.rule': 'Linie',
  'token.rule.hint': 'Rahmen und Trenner.',
  'token.ruleFaint': 'Linie, blass',
  'token.accent': 'Akzent',
  'token.warn': 'Warnung',
  'token.warn.hint': 'Überfällige Daten, zerstörende Aktionen.',
  'token.ok': 'Erfolg',
  'token.ok.hint': 'Ganztägige Termine, aktive Buchungslinks.',
  'token.priHigh': 'Hoch',
  'token.priMed': 'Mittel',
  'token.priLow': 'Niedrig',
  'token.serif': 'Lesen',
  'token.serif.hint': 'Titel und Überschriften.',
  'token.sans': 'Oberfläche',
  'token.sans.hint': 'Fließtext und Bedienelemente.',
  'token.mono': 'Mono',
  'token.mono.hint': 'Beschriftungen, Daten, Zahlen.',
  'token.radius': 'Ecken',
  'token.fsScale': 'Textgröße',
  'token.labelCase': 'Beschriftungen',
  'token.labelCase.hint': 'Schaltflächen, Mikrobeschriftungen und Spaltenköpfe.',
  'token.labelCase.uppercase': 'Großbuchstaben',
  'token.labelCase.none': 'Normale Schreibweise',
  'token.tracking': 'Laufweite',
  'token.tracking.hint': 'Buchstabenabstand bei genau diesen Beschriftungen. 0 schließt ihn.',
  'token.gutter': 'Seitenabstand',
  'token.gutter.hint': 'Waagerechte Luft um den Inhalt.',
  'token.rowY': 'Zeilenhöhe',
  'token.rowY.hint': 'Senkrechter Innenabstand in einer Aufgabenzeile.',
  'tokenGroup.Surfaces': 'Flächen',
  'tokenGroup.Text': 'Text',
  'tokenGroup.Rules': 'Linien',
  'tokenGroup.Accents': 'Akzente',
  'tokenGroup.Priority': 'Priorität',
  'tokenGroup.Shape': 'Form',
  'tokenGroup.Density': 'Dichte',
  'tokenGroup.Type': 'Schrift',
  'appear.atCap': 'Du kannst {max} Themes behalten — lösch zuerst eines.',
  'appear.copySuffix': '{name} Kopie',
  'appear.custom': 'Eigenes',
  'appear.notATheme': 'Diese Datei ist kein Smylte-Theme.',
  'appear.title': 'Erscheinungsbild',
  // „Theme“ stays: it is what the export file is called (.smylte-theme.json)
  // and what the setting is named everywhere else in this app. „Design“
  // would be a different word for the same thing on the same screen.
  'appear.theme': 'Theme',
  'appear.smylteDefault': 'Smylte (Standard)',
  'appear.builtIn': 'Mitgeliefert',
  'appear.yourThemes': 'Deine Themes',
  'appear.duplicate': 'Duplizieren',
  'appear.rename': 'Umbenennen',
  'appear.export': 'Exportieren',
  'appear.import': 'Importieren',
  'appear.themeName': 'Theme-Name',
  'appear.presetHint': '{name} ist ein mitgeliefertes Theme. Änder unten irgendetwas, und es zweigt in ein eigenes Theme ab.',
  'appear.editingHint': 'Du bearbeitest dieses Theme. Smyltes eigenes Design wird nie verändert — du kannst jederzeit zurückwechseln.',
  'appear.shippedHint': 'Smyltes mitgeliefertes Design. Änder unten irgendetwas, und es zweigt in ein eigenes Theme ab.',
  'appear.editingMode': 'Bearbeitungsmodus',
  'appear.light': 'Hell',
  'appear.dark': 'Dunkel',
  'appear.builtInTheme': 'Mitgeliefertes Theme',
  // {mode} is „hell“ or „dunkel“ — appear.lightLower / appear.darkLower, the
  // lowercase pair, because it lands mid-sentence here and as a button label
  // above. German capitalises nouns, not adjectives, so these two stay small.
  'appear.overrides': {
    one: '{count} Abweichung in {mode}',
    other: '{count} Abweichungen in {mode}',
  },
  'appear.lightLower': 'hell',
  'appear.darkLower': 'dunkel',
  'appear.resetMode': '{mode} zurücksetzen',
  'appear.deleteTheme': 'Theme löschen',
  'appear.done': 'Fertig',
  'appear.resetToken': 'Zurück zum Smylte-Wert',
  'appear.resetNamed': '{token} zurücksetzen',
  'appear.pickColor': '{token} — eine Farbe wählen',
  'appear.customFont': 'Eigene ({family})',
  // ── the public booking page ─────────────────────────────────────────────────
  'book.loading': 'Die freien Zeiten werden geladen…',
  'book.notFound': 'Dieser Buchungslink ist nicht mehr verfügbar.',
  'book.notFoundHint': 'Er wurde vielleicht abgeschaltet oder entfernt. Frag die Person, die ihn geschickt hat, nach einem neuen Link.',
  'book.unavailable': 'Diese Seite konnte gerade nicht geladen werden.',
  'book.unavailableHint': 'Mit dem Link ist wahrscheinlich alles in Ordnung — unterwegs ist etwas schiefgegangen. Versuch es gleich noch einmal.',
  'book.tryAgain': 'Nochmal versuchen',
  'book.confirmed': 'Bestätigt',
  'book.range': '{from}–{to}',
  'book.youAreBooked': 'Gebucht, {name}. Zeiten in {tz}.',
  'book.bookATime': 'Zeit buchen',
  'book.minutes': '{n} Min.',
  'book.timesShownIn': 'Zeiten in {tz}',
  'book.noTimes': 'Gerade sind keine Zeiten frei — schau später noch einmal.',
  'book.hostBusy': 'Zu dieser Zeit ist der Gastgeber belegt',
  'book.busyRange': 'Belegt {from}–{to}',
  'book.change': 'Ändern',
  'book.yourName': 'Dein Name',
  'book.email': 'E-Mail',
  'book.notes': 'Notizen (optional)',
  'book.notesPlaceholder': 'Etwas, das der Gastgeber wissen sollte?',
  'book.booking': 'Wird gebucht…',
  'book.confirm': 'Buchung bestätigen',
  'book.taken': 'Diese Zeit wurde gerade vergeben — bitte wähl eine andere.',
  // ── today — the tomorrow suggestion ─────────────────────────────────────────
  'today.sug.tomorrow': 'Morgen fällig',
  // ── home — the day-plan module ──────────────────────────────────────────────
  'module.day_plan': 'Tagesplan',
  'module.day_plan.blurb': 'Was du dir für heute vorgenommen hast, dazu deine Gewohnheiten und Notizen.',
  'home.planEmpty': 'Heute steht noch nichts an. Plan ihn im Heute-Tab.',
  'home.planUncheck': '{entry} abhaken rückgängig',
  'home.planCheck': '{entry} abhaken',
}
