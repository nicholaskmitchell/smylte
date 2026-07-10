#!/usr/bin/env bash
# Empirical check (on SCRATCH, never production): when the Task Manager creates
# VTODO-only task collections alongside normal VEVENT calendars, how do Søren's
# calendar tools behave? Søren's CalendarList keys on resourcetype=calendar;
# a VTODO collection is *also* a calendar collection, so it will appear. We want
# to confirm that (a) it appears but (b) never surfaces as an event and (c)
# Radicale's component-set enforcement means a stray VEVENT PUT fails safely.
set -uo pipefail
B=http://127.0.0.1:5233
A=(-u testuser:testpass -s)

echo "### 1. MKCALENDAR a normal VEVENT calendar (what Søren expects)"
curl "${A[@]}" -X MKCALENDAR "$B/testuser/cal-events/" -w " -> HTTP %{http_code}\n" \
  -H 'Content-Type: application/xml' --data '<?xml version="1.0" encoding="utf-8"?>
<C:mkcalendar xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
 <D:set><D:prop>
  <D:displayname>Events</D:displayname>
  <C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
 </D:prop></D:set></C:mkcalendar>'

echo "### 2. MKCALENDAR a VTODO-ONLY task collection (what the Task Manager makes)"
curl "${A[@]}" -X MKCALENDAR "$B/testuser/tasks-inbox/" -w " -> HTTP %{http_code}\n" \
  -H 'Content-Type: application/xml' --data '<?xml version="1.0" encoding="utf-8"?>
<C:mkcalendar xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
 <D:set><D:prop>
  <D:displayname>Inbox</D:displayname>
  <C:supported-calendar-component-set><C:comp name="VTODO"/></C:supported-calendar-component-set>
 </D:prop></D:set></C:mkcalendar>'

echo
echo "### 3. Søren's CalendarList PROPFIND (Depth:1, displayname+resourcetype)"
curl "${A[@]}" -X PROPFIND "$B/testuser/" -H 'Depth: 1' -H 'Content-Type: application/xml' \
  --data '<?xml version="1.0"?><D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:displayname/><D:resourcetype/><C:supported-calendar-component-set/></D:prop></D:propfind>' \
  | python3 -c 'import sys,xml.dom.minidom as m; print(m.parseString(sys.stdin.read()).toprettyxml()[:2500])'

echo "### 4. Søren's CalendarListEvents calendar-query (VEVENT time-range) AGAINST the VTODO list"
curl "${A[@]}" -X REPORT "$B/testuser/tasks-inbox/" -H 'Depth: 1' -H 'Content-Type: application/xml' \
  -w "\n -> HTTP %{http_code}\n" \
  --data '<?xml version="1.0"?><C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/><C:calendar-data/></D:prop><C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT"><C:time-range start="20200101T000000Z" end="20300101T000000Z"/></C:comp-filter></C:comp-filter></C:filter></C:calendar-query>'

echo "### 5. Does Radicale REJECT a stray VEVENT PUT into the VTODO-only list? (component-set enforcement)"
curl "${A[@]}" -X PUT "$B/testuser/tasks-inbox/stray-event.ics" -w " -> HTTP %{http_code}\n" \
  -H 'Content-Type: text/calendar' --data $'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//probe//EN\r\nBEGIN:VEVENT\r\nUID:stray-1\r\nSUMMARY:stray\r\nDTSTART:20260101T090000Z\r\nDTEND:20260101T100000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
