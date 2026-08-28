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
}
