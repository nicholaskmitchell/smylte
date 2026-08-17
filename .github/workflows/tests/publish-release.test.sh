#!/usr/bin/env bash
# Tests the publish step of desktop-release.yml against a stub `gh`.
#
# That step is the only code in the repository that publishes something the
# outside world installs, and its failure mode is not a red build: on
# 2026-08-17 a GitHub 503 hit the notes edit AFTER the assets had uploaded, so
# `desktop-latest` sat with new binaries under notes naming the previous commit.
# A retry wrapper is exactly the kind of code that looks obviously right and is
# not — writing this file caught a real bug in it (annotations on stdout, which
# corrupted the `$(retry ...)` capture and silently took the create path).
#
# It runs the REAL step: the `run:` block is read out of the YAML, so the thing
# under test cannot drift from the thing that ships. Only `gh` and `sleep` are
# stubbed.
#
# Run it directly: .github/workflows/tests/publish-release.test.sh
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORKFLOW="$HERE/../desktop-release.yml"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

python3 - "$WORKFLOW" "$WORK/publish.sh" <<'PY'
import sys, yaml, pathlib
wf = yaml.safe_load(open(sys.argv[1]))
steps = wf["jobs"]["release"]["steps"]
step = next(s for s in steps if s.get("name") == "Publish the rolling release")
pathlib.Path(sys.argv[2]).write_text(step["run"])
PY
bash -n "$WORK/publish.sh" || { echo "publish step is not valid bash"; exit 1; }

# ── the stub ────────────────────────────────────────────────────────────────
# Knobs are env vars so each case is one line. FAIL_PROBE_TIMES covers the
# existence check whichever call is used to make it, so this file still tests a
# rewrite of that part rather than one particular implementation of it.
run_case() {
  (
    set -uo pipefail
    export GITHUB_SHA=deadbeefcafe1234
    export GITHUB_REPOSITORY=nicholaskmitchell/smylte
    _STUB=$(mktemp -d)
    : "${FAIL_PROBE_TIMES:=0}" "${API_ANSWER:=present}" "${FAIL_UPLOAD_TIMES:=0}"
    : "${FAIL_EDIT_TIMES:=0}" "${FAIL_CREATE_TIMES:=0}" "${EDIT_WRITES_SHA:=1}"

    # Starts stale, the way the real release did after the 503.
    echo "Rolling desktop build from 0000000000000000." > "$_STUB/body"

    # Silent, like the real one — a chatty stub would hide a stdout bug.
    sleep() { :; }

    _bump() {
      local f="$_STUB/$1" n=0
      [ -f "$f" ] && n=$(cat "$f")
      n=$((n + 1)); echo "$n" > "$f"; echo "$n"
    }

    _probe() {
      local n; n=$(_bump probe); echo "  [gh] $1 (call $n)" >&2
      if [ "$n" -le "$FAIL_PROBE_TIMES" ]; then
        echo "gh: No server is currently available to service your request. (HTTP 503)" >&2
        return 1
      fi
      [ "$API_ANSWER" = absent ] && { echo "gh: Not Found (HTTP 404)" >&2; return 1; }
      return 0
    }

    gh() {
      local n
      case "$1 ${2:-}" in
        "api repos/nicholaskmitchell/smylte/releases/tags/desktop-latest")
          _probe "api tags" && { echo '{"tag_name":"desktop-latest"}'; return 0; }; return 1 ;;
        "release view")
          # --json is the post-condition read; bare is an existence probe.
          if [[ "$*" == *--json* ]]; then cat "$_STUB/body"; return 0; fi
          _probe "release view" || return 1
          echo desktop-latest; return 0 ;;
        "release upload")
          n=$(_bump upload); echo "  [gh] release upload (call $n)" >&2
          [ "$n" -le "$FAIL_UPLOAD_TIMES" ] && { echo "gh: HTTP 503" >&2; return 1; }
          return 0 ;;
        "release edit")
          n=$(_bump edit); echo "  [gh] release edit (call $n)" >&2
          [ "$n" -le "$FAIL_EDIT_TIMES" ] && { echo "gh: HTTP 503" >&2; return 1; }
          [ "$EDIT_WRITES_SHA" = 1 ] && echo "Rolling desktop build from ${GITHUB_SHA}." > "$_STUB/body"
          return 0 ;;
        "release create")
          n=$(_bump create); echo "  [gh] release create (call $n)" >&2
          [ "$n" -le "$FAIL_CREATE_TIMES" ] && { echo "gh: HTTP 503" >&2; return 1; }
          # What the real API says when the tag is already there.
          [ "$API_ANSWER" = present ] && { echo "gh: Validation Failed: already_exists (HTTP 422)" >&2; return 1; }
          echo "Rolling desktop build from ${GITHUB_SHA}." > "$_STUB/body"
          return 0 ;;
        *) echo "  [gh] UNSTUBBED: $*" >&2; return 127 ;;
      esac
    }

    # `bash -e {0}` is the shell GitHub Actions runs a `run:` block with.
    ( set -e; source "$WORK/publish.sh" )
  )
}

# ── the cases ───────────────────────────────────────────────────────────────
pass=0; fail=0

case_is() {
  local name="$1" want_exit="$2" want_trace="$3"; shift 3
  local out code
  out=$(env "$@" bash -c "$(declare -f run_case); WORK=$WORK; run_case" 2>&1); code=$?
  if [ "$code" = "$want_exit" ] && grep -qE "$want_trace" <<<"$out"; then
    echo "ok   $name"; pass=$((pass + 1))
  else
    echo "FAIL $name — exit $code (wanted $want_exit), trace /$want_trace/"
    sed 's/^/       /' <<<"$out"; fail=$((fail + 1))
  fi
}

# Nothing wrong: the release exists, both calls land.
case_is "publishes onto the existing release"            0 'release edit'
# The 2026-08-17 outage, exactly: a transient on the notes edit.
case_is "a transient on the edit is retried, not fatal"  0 'release edit \(call 3\)' FAIL_EDIT_TIMES=2
case_is "a transient on the upload is retried"           0 'release upload \(call 2\)' FAIL_UPLOAD_TIMES=1
# A first run, or someone having deleted the release: 404 is an ANSWER.
case_is "a genuine 404 still creates the release"        0 'release create' API_ANSWER=absent
# The retries must not paper over a real outage.
case_is "a sustained outage fails the job"               1 'release edit \(call 5\)' FAIL_EDIT_TIMES=99
# The half-updated state must be red, not green-and-wrong.
case_is "notes that miss the commit fail the job"        1 'half-updated' EDIT_WRITES_SHA=0
# A transient on the existence check must not read as "no release yet" — that
# sends the step into `gh release create`, which dies with already_exists.
case_is "a transient probe does not become a create"     0 'release upload' FAIL_PROBE_TIMES=2
case_is "a dead probe fails rather than guessing"        1 'EXIT|503' FAIL_PROBE_TIMES=99

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
