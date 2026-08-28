// The source text. Every string the app shows, in the language it was written
// in — and the list of keys every other catalogue is checked against, because a
// key English lacks is a key nobody wrote rather than one nobody translated.
//
// THE VALUES HERE ARE TODAY'S STRINGS, VERBATIM. That is not tidiness: some
// 500 test assertions match on this text (`getByLabelText('Add to today')`,
// `getByText('Nothing to do here.')`), the provider defaults to English, and a
// component rendered outside it reads exactly what it read before — so
// extracting a string costs no test change, and a "harmless" rewording while
// extracting would cost several. Reword in a commit of its own.
//
// Flat dotted keys, sorted by surface, so a catalogue diffs against another
// line by line. Placeholders are `{name}`; a message that changes with a count
// is an object of `Intl.PluralRules` categories — see `./index.ts`.

export const en = {
  // ── the shell ────────────────────────────────────────────────────────────
  'app.settings': 'Settings',
  'app.retry': 'Retry',
  'app.dismiss': 'Dismiss',
  'app.back': 'Back',
  'app.closeSettings': 'Close settings',

  'tab.today': 'Today',
  'tab.home': 'Home',
  'tab.tasks': 'Tasks',
  'tab.calendar': 'Calendar',
  'tab.scheduling': 'Scheduling',

  'tabs.opensOn': 'Opens on',
  'tabs.lastUsed': 'Last used tab',
  'tabs.moveLeft': 'Move {tab} left',
  'tabs.moveRight': 'Move {tab} right',
  'tabs.hint': 'The order here is the order across the top. \u201CLast used tab\u201D '
    + 'reopens wherever you left off, on every device signed into this account.',

  // ── settings ─────────────────────────────────────────────────────────────
  'settings.sections': 'Settings sections',
  'settings.section.general': 'General',
  'settings.section.appearance': 'Appearance',
  'settings.section.calendar': 'Calendar',
  'settings.section.tasks': 'Tasks',
  'settings.section.account': 'Account',

  'settings.tabs': 'Tabs',

  'settings.language': 'Language',
  'settings.language.aria': 'The language the app is shown in',
  'settings.language.hint': 'The language the app writes in, and the calendar '
    + 'it counts days by. Your lists, tasks and events keep whatever you '
    + 'called them.',

  'settings.clock': 'Clock',
  'settings.clock.aria': '12- or 24-hour clock',
  'settings.clock.hint': 'The clock covers every time the app draws itself. '
    + 'Date and time pickers are drawn by the browser — Chrome, Edge and the '
    + 'Windows app follow this setting, Firefox follows your system’s.',
  'clock.12h': '12-hour',
  'clock.24h': '24-hour',

  'settings.workingDay': 'Working day',

  'settings.timezone': 'Time zone',
  'settings.homeTimezone': 'Home timezone',
  'settings.homeTimezone.aria': 'Timezone your events are written in',
  'settings.homeTimezone.title': 'Which clock your events are written on. '
    + 'Scheduling links use it to know when you are really busy.',
  'settings.notSet': 'Not set',

  'settings.theme': 'Theme',
  'theme.dark': 'Dark',
  'theme.light': 'Light',
  'settings.appearance': 'Appearance',
  'settings.appearance.customize': 'Customize…',
  'settings.appearance.aria': 'Customize appearance',
  'settings.appearance.hint': 'Customize opens the full editor over the design '
    + 'system — every color token, the corner radius, the text scale and the '
    + 'type families — and saves what you make as a named theme.',

  'settings.calendarWindow': 'Calendar window',
  'settings.calendarFit.aria': 'Fixed or dynamic calendar grid',
  'settings.calendarFit.title': 'Fixed keeps every week the same height; a day '
    + 'with more than fits collapses into “+N more” instead of '
    + 'stretching its week.',
  'settings.calendarFit.hint': 'A fixed calendar window fits the whole month in '
    + 'the pane: every week is the same height, and a day with more than fits '
    + 'collapses into “+N more”. Dynamic lets a busy week grow and '
    + 'the grid scroll.',
  'calendarFit.fixed': 'Fixed',
  'calendarFit.dynamic': 'Dynamic',

  'settings.archivedCalendars': 'Archived calendars',
  'settings.archived.hint': 'Archiving hides a calendar without deleting it. '
    + 'Lists and calendars live on the Radicale CalDAV server — changes there '
    + 'show up in every connected client, but an archive is Smylte’s own '
    + 'and the collection stays on the wire.',

  'settings.completedTasks': 'Completed tasks',
  'settings.completedTasks.shown': 'Shown',
  'settings.completedTasks.hidden': 'Hidden',
  'settings.completedTasks.hint': 'Whether completed tasks stay in the main '
    + 'view. The sidebar’s “View completed” works either way.',

  'settings.signedInAs': 'Signed in as',
  'settings.staySignedIn': 'Stay signed in',
  'settings.staySignedIn.aria': 'How long to stay signed in',
  'settings.session.hint': 'A shorter sign-in applies at once, on this device '
    + 'and any other. A longer one starts from your next sign-in.',
  'session.1d': '1 day',
  'session.7d': '7 days',
  'session.30d': '30 days',
  'session.never': 'Never',
  'settings.connectedApps': 'Connected apps',
  'settings.logout': 'Log out',
} as const
