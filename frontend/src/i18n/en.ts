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

  // ── archived calendars ──────────────────────────────────────────────────────
  'arch.loading': 'Loading…',
  'arch.loadFailed': 'Couldn’t load your archived calendars.',
  'arch.none': 'No archived calendars.',
  'arch.viewEvents': 'View events',
  'arch.restore': 'Restore',
  'arch.restoreCalendar': 'Restore calendar',
  'arch.showing': 'Showing events {from} – {to}',
  'arch.calLoadFailed': 'Couldn’t load this calendar’s events.',
  'arch.noEvents': 'No events in this window.',
  'common.allDay': 'all day',
  'common.untitled': '(untitled)',
  // ── connected apps ──────────────────────────────────────────────────────────
  'conn.readWrite': 'Read and write',
  'conn.readOnly': 'Read only',
  'conn.noAccess': 'No access',
  'conn.loading': 'Loading…',
  'conn.loadFailed': 'Couldn’t load your connected applications. Any grants you have are still live — this list could not be read, not emptied.',
  'conn.none': 'Nothing is connected. Applications you connect through the MCP endpoint appear here.',
  'conn.anApplication': 'An application',
  'conn.connectedAt': 'Connected {when}',
  'conn.keep': 'Keep',
  'conn.disconnect': 'Disconnect',
  'conn.hint': 'Disconnecting takes effect at once — the application has to be reconnected, and approved again, before it can read anything.',
  // ── capacity ────────────────────────────────────────────────────────────────
  'capacity.mostDays': 'Most days',
  'capacity.notSet': 'not set',
  'capacity.defaultDay': 'the default working day',
  'capacity.sameAsMostDays': 'same as most days',
  'capacity.workingTimeFor': 'Working time for {name}',
  'capacity.hint': 'Say it as {short} or {long} minutes. A day you have not given a length is never counted against you — the Today tab simply says nothing about how full it is.',
  // ── sign in ─────────────────────────────────────────────────────────────────
  'login.invalid': 'Invalid credentials',
  'login.username': 'Username',
  'login.password': 'Password',
  'login.submit': 'Sign in',
  // ── task modal ──────────────────────────────────────────────────────────────
  'taskModal.add': 'Add task',
  'taskModal.edit': 'Task',
  'common.close': 'Close',
  'taskModal.title': 'Title',
  'taskModal.notes': 'Notes',
  'taskModal.addMultiple': 'Add multiple',
  'common.delete': 'Delete',
  'common.add': 'Add',
  'common.save': 'Save',
} as const
