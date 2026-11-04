#!/usr/bin/env bash
# Tests .github/workflows/scripts/record-checksums.sh against a stub `gh`.
#
# The script writes the lines the desktop clients check their downloads
# against, so what it must get right is the notes it leaves behind: the publish
# step's lines kept as they were, one checksum per file, a previous run's block
# replaced rather than repeated, and a failed edit red rather than silent.
#
# Run it directly: .github/workflows/tests/record-checksums.test.sh
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SCRIPT="$HERE/../scripts/record-checksums.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

WEB=sha256:da6acd88ab1b437e22b7e56f86a2f070e6c3c2b37d7736ceb2406c5068357e7b
EXE=sha256:35e3082f34f8c669a1a7d5c27b1090ba5fb39273ead3da733d1ec12b40f611f8
LINUX=sha256:efeb0b9590fd042fa728c49496ccbffce83da465092982e3589cb02dd6aad139
HEADING="Checksums (the desktop clients check each download against these):"

# The stub `gh`, on PATH. Knobs: FAIL_API_TIMES (the release read),
# FAIL_EDIT_TIMES, EDIT_DROPS (a line the edit loses), NO_WEB_DIGEST,
# FAIL_DISPATCH. The release lives in $STATE/body.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
bump() { local f="$STATE/$1" n=0; [ -f "$f" ] && n=$(cat "$f"); n=$((n + 1)); echo "$n" > "$f"; echo "$n"; }
case "$1 ${2:-}" in
  "api repos/nicholaskmitchell/smylte/releases/tags/desktop-latest")
    n=$(bump api); echo "  [gh] api release (call $n)" >&2
    if [ "$n" -le "${FAIL_API_TIMES:-0}" ]; then
      echo '{"message":"Server Error"}'; echo "gh: Server Error (HTTP 500)" >&2; exit 1
    fi
    python3 - "$STATE/body" <<'PY'
import json, os, sys
web = None if os.environ.get("NO_WEB_DIGEST") == "1" else os.environ["WEB"]
print(json.dumps({"body": open(sys.argv[1]).read(), "assets": [
    {"name": "Smylte.exe", "digest": os.environ["EXE"]},
    {"name": "smylte-web.zip", "digest": web},
    {"name": "Smylte-linux-x86_64", "digest": os.environ["LINUX"].upper().replace("SHA256", "sha256")},
    {"name": "Smylte-android.apk"},
]}))
PY
    ;;
  "release edit")
    n=$(bump edit); echo "  [gh] release edit (call $n)" >&2
    [ "$n" -le "${FAIL_EDIT_TIMES:-0}" ] && { echo "gh: HTTP 503" >&2; exit 1; }
    while [ "$#" -gt 1 ]; do [ "$1" = --notes ] && break; shift; done
    printf '%s' "$2" | { [ -n "${EDIT_DROPS:-}" ] && grep -vF -- "$EDIT_DROPS" || cat; } > "$STATE/body"
    ;;
  "workflow run")
    echo "  [gh] workflow run ${*:3}" >&2
    [ "${FAIL_DISPATCH:-0}" = 1 ] && { echo "gh: HTTP 403" >&2; exit 1; }
    ;;
  *) echo "  [gh] UNSTUBBED: $*" >&2; exit 127 ;;
esac
STUB
chmod +x "$WORK/bin/gh"
printf '#!/bin/sh\n' > "$WORK/bin/sleep"; chmod +x "$WORK/bin/sleep"

PUBLISHED="Rolling client build from deadbeef.

Client source tree: 1111111111111111111111111111111111111111
Linux client key: 2222222222222222222222222222222222222222"

pass=0; fail=0

# run_case NAME WANT_EXIT START_BODY CHECK [KNOB=VALUE...]
# CHECK is a bash expression over $body (the notes afterwards) and $out (the trace).
run_case() {
  local name="$1" want="$2" start="$3" check="$4"; shift 4
  local state out code body
  state=$(mktemp -d "$WORK/case.XXXX")
  printf '%s' "$start" > "$state/body"
  out=$(env PATH="$WORK/bin:$PATH" STATE="$state" WEB="$WEB" EXE="$EXE" LINUX="$LINUX" \
    GITHUB_REPOSITORY=nicholaskmitchell/smylte "$@" bash "$SCRIPT" 2>&1); code=$?
  body=$(cat "$state/body")
  if [ "$code" = "$want" ] && eval "$check"; then
    echo "ok   $name"; pass=$((pass + 1))
  else
    echo "FAIL $name — exit $code (wanted $want)"
    sed 's/^/       /' <<<"$out"; sed 's/^/       [body] /' <<<"$body"; fail=$((fail + 1))
  fi
}

EXPECTED="$PUBLISHED

$HEADING
- Smylte-linux-x86_64: $LINUX
- Smylte.exe: $EXE
- smylte-web.zip: $WEB"

run_case "writes one line per digest under the publish step's notes" 0 "$PUBLISHED" \
  '[ "$body" = "$EXPECTED" ] && grep -q "workflow run sync-issues.yml" <<<"$out"'
run_case "a previous run's block is replaced, not repeated" 0 \
  "$PUBLISHED

$HEADING
- smylte-web.zip: sha256:0000000000000000000000000000000000000000000000000000000000000000" \
  '[ "$body" = "$EXPECTED" ]'
run_case "notes saved with Windows line ends lose their old block too" 0 \
  "$(printf '%s\r\n\r\n%s\r\n- smylte-web.zip: sha256:00\r\n' "Rolling client build from deadbeef." "$HEADING")" \
  '[ "$(grep -c "^$HEADING" <<<"$body")" = 1 ] && grep -qx -- "- smylte-web.zip: $WEB" <<<"$body"'
run_case "a transient on the read is retried" 0 "$PUBLISHED" \
  '[ "$body" = "$EXPECTED" ]' FAIL_API_TIMES=2
run_case "a transient on the edit is retried" 0 "$PUBLISHED" \
  '[ "$body" = "$EXPECTED" ]' FAIL_EDIT_TIMES=2
run_case "a dead edit fails the job" 1 "$PUBLISHED" \
  'grep -q "giving up" <<<"$out"' FAIL_EDIT_TIMES=99
run_case "notes that lost a checksum fail the job" 1 "$PUBLISHED" \
  'grep -q "do not record" <<<"$out"' EDIT_DROPS="Smylte.exe: sha256"
run_case "no digest for the web build writes nothing, and is not a failure" 0 "$PUBLISHED" \
  '[ "$body" = "$PUBLISHED" ] && grep -q "no checksums written" <<<"$out"' NO_WEB_DIGEST=1
run_case "a sync that will not start is a warning" 0 "$PUBLISHED" \
  '[ "$body" = "$EXPECTED" ] && grep -q "::warning::could not start" <<<"$out"' FAIL_DISPATCH=1

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
