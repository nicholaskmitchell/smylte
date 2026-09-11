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
REPO=$(cd "$HERE/../../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# The step decides whether to re-publish the exe by comparing the client's
# source tree at HEAD with the one recorded on the release, so it runs `git`
# against this checkout — from the repository root, as the release job does.
cd "$REPO"
CLIENT_TREE=$(git rev-parse "HEAD:desktop/Smylte.Desktop")
# Derived the same way the step derives it, from the same checkout, so a change
# to how the key is composed fails here rather than silently re-publishing the
# Linux binary on every push forever.
LINUX_KEY=$(printf '%s %s\n' "$CLIENT_TREE" "$(git rev-parse "HEAD:desktop/Smylte.Desktop.Linux")" \
  | git hash-object --stdin)

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
    : "${FAIL_EDIT_TIMES:=0}" "${FAIL_CREATE_TIMES:=0}" "${EDIT_WRITES_SHA:=1}" "${EDIT_DROPS_TREE:=0}"
    # The body fetch is the one call in the step whose failure the code is
    # allowed to swallow, so it is the one that most needs a knob.
    : "${FAIL_BODY_TIMES:=0}"
    # What the release already holds: its asset names, and the client source
    # tree its notes record (empty = a release from before that line existed).
    : "${ASSETS:=smylte-web.zip Smylte.exe Smylte-linux-x86_64}" "${PUBLISHED_TREE:=}"
    : "${PUBLISHED_LINUX_KEY:=}" "${EDIT_DROPS_LINUX_KEY:=0}"

    # Starts stale, the way the real release did after the 503.
    {
      echo "Rolling desktop build from 0000000000000000."
      [ -n "$PUBLISHED_TREE" ] && echo "Client source tree: $PUBLISHED_TREE"
      [ -n "$PUBLISHED_LINUX_KEY" ] && echo "Linux client key: $PUBLISHED_LINUX_KEY"
    } > "$_STUB/body"

    # The notes the step passes to `gh release edit/create --notes`, so the
    # stub's release carries what the step wrote and the post-conditions read
    # back exactly what the real API would hand them.
    _notes_arg() {
      while [ "$#" -gt 1 ]; do
        [ "$1" = --notes ] && { printf '%s\n' "$2"; return 0; }
        shift
      done
      return 1
    }

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
          # --json reads the release (assets, or the body for the decision and
          # the post-condition); bare is an existence probe.
          if [[ "$*" == *"--json assets"* ]]; then printf '%s\n' $ASSETS; return 0; fi
          if [[ "$*" == *--json* ]]; then
            # `bodyfetch`, not `body`: the counter and the release body would
            # otherwise be the same file under $_STUB.
            n=$(_bump bodyfetch); echo "  [gh] release view --json body (call $n)" >&2
            [ "$n" -le "$FAIL_BODY_TIMES" ] && { echo "gh: HTTP 503" >&2; return 1; }
            cat "$_STUB/body"; return 0
          fi
          _probe "release view" || return 1
          echo desktop-latest; return 0 ;;
        "release upload")
          # The files are in the trace: which of them went up IS the behaviour
          # under test for the exe cases.
          n=$(_bump upload); echo "  [gh] release upload (call $n): ${*:3}" >&2
          [ "$n" -le "$FAIL_UPLOAD_TIMES" ] && { echo "gh: HTTP 503" >&2; return 1; }
          return 0 ;;
        "release edit")
          n=$(_bump edit); echo "  [gh] release edit (call $n)" >&2
          [ "$n" -le "$FAIL_EDIT_TIMES" ] && { echo "gh: HTTP 503" >&2; return 1; }
          # EDIT_DROPS_TREE: the notes land without the tree line — a half-
          # updated release of the other kind, one the NEXT run would read as
          # "unrecorded" and re-upload the exe over.
          if [ "$EDIT_WRITES_SHA" = 1 ]; then
            _notes_arg "$@" \
              | { [ "$EDIT_DROPS_TREE" = 1 ] && grep -v 'Client source tree' || cat; } \
              | { [ "$EDIT_DROPS_LINUX_KEY" = 1 ] && grep -v 'Linux client key' || cat; } \
              > "$_STUB/body"
          fi
          return 0 ;;
        "release create")
          n=$(_bump create); echo "  [gh] release create (call $n): ${*:3}" >&2
          [ "$n" -le "$FAIL_CREATE_TIMES" ] && { echo "gh: HTTP 503" >&2; return 1; }
          # What the real API says when the tag is already there.
          [ "$API_ANSWER" = present ] && { echo "gh: Validation Failed: already_exists (HTTP 422)" >&2; return 1; }
          _notes_arg "$@" > "$_STUB/body"
          return 0 ;;
        *) echo "  [gh] UNSTUBBED: $*" >&2; return 127 ;;
      esac
    }

    # `bash -e {0}` is the shell GitHub Actions runs a `run:` block with —
    # and `-e` is ALL of it. `-u` and `-o pipefail` are set above for the
    # harness's own code and must be turned back off here, or the step under
    # test runs stricter than the step that ships: with pipefail on, a scrape
    # whose fetch failed is a failed assignment, and with it off — as in
    # production — it is an empty string that reads as "unrecorded". That is a
    # difference between red and green-and-wrong, and it hid exactly that bug.
    ( set +u +o pipefail; set -e; source "$WORK/publish.sh" )
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
# The one call the step is allowed to swallow. `published=$(retry ... | sed |
# head -1) || return 1` cannot fail — a pipeline's status is head's — so a
# body fetch that 503s five times produced an empty key, which reads as
# "unrecorded", which republishes BOTH binaries and exits 0. Everything else
# about that run looks like a clean publish.
# Ten, not 99: five attempts each for the two publish_reason fetches, and the
# post-condition's own fetch left working. Failing that one too would make the
# case pass for the wrong reason — `BODY=$(retry ...)` is a bare assignment and
# dies under `set -e` whatever the decision above it did.
case_is "a dead body fetch does not republish"          1 'giving up' \
  FAIL_BODY_TIMES=10 PUBLISHED_TREE="$CLIENT_TREE" PUBLISHED_LINUX_KEY="$LINUX_KEY"

# ── which files go up ───────────────────────────────────────────────────────
# The exe is a self-contained bundle that is never the same bytes twice, and
# the client tells "a new client" by digest — so re-uploading it on every push
# told every Windows user to download 69 MB that changed nothing. The web zip
# goes up every run; the exe only when desktop/Smylte.Desktop differs from what
# the published exe was built from, which the notes record.
ZIP='artifacts/web/smylte-web\.zip'
EXE='artifacts/client/Smylte\.exe'
LNX='artifacts/client-linux/Smylte-linux-x86_64'
BOTH="PUBLISHED_TREE=$CLIENT_TREE PUBLISHED_LINUX_KEY=$LINUX_KEY"

case_is "an unchanged client is not re-published"        0 "release upload \(call 1\): desktop-latest $ZIP --clobber" PUBLISHED_TREE="$CLIENT_TREE" PUBLISHED_LINUX_KEY="$LINUX_KEY"
case_is "notes that lose the tree line fail the job"    1 'do not record the client source tree' EDIT_DROPS_TREE=1
case_is "a changed client is published"                  0 "release upload \(call 1\): desktop-latest $ZIP $EXE $LNX --clobber" PUBLISHED_TREE=0123456789abcdef0123456789abcdef01234567
case_is "a release from before the tree was recorded gets the exe once" 0 "release upload .*$EXE"
case_is "a release missing the exe gets it even when the tree matches"  0 "release upload .*$EXE" PUBLISHED_TREE="$CLIENT_TREE" PUBLISHED_LINUX_KEY="$LINUX_KEY" ASSETS="smylte-web.zip Smylte-linux-x86_64"
case_is "a forced dispatch publishes the client regardless"             0 "release upload .*$EXE" PUBLISHED_TREE="$CLIENT_TREE" PUBLISHED_LINUX_KEY="$LINUX_KEY" CLIENT_PUBLISH=force
case_is "a first release carries all three"              0 "release create \(call 1\): desktop-latest $ZIP $EXE $LNX" API_ANSWER=absent

# ── and the same decision for the Linux binary, taken separately ────────────
# The two keys cover overlapping trees: the Linux client LINKS the shared
# sources, so a change under desktop/Smylte.Desktop moves BOTH keys while a
# change under desktop/Smylte.Desktop.Linux moves only its own. A single shared
# key would get the second case wrong in the expensive direction — telling every
# Windows user to download 69 MB because a GTK file moved.
case_is "a changed Linux client is published without the exe" 0 "release upload \(call 1\): desktop-latest $ZIP $LNX --clobber" PUBLISHED_TREE="$CLIENT_TREE" PUBLISHED_LINUX_KEY=0123456789abcdef0123456789abcdef01234567
case_is "a release missing the Linux binary gets it even when the key matches" 0 "release upload .*$LNX" PUBLISHED_TREE="$CLIENT_TREE" PUBLISHED_LINUX_KEY="$LINUX_KEY" ASSETS="smylte-web.zip Smylte.exe"
case_is "a release from before the Linux key was recorded gets it once" 0 "release upload .*$LNX" PUBLISHED_TREE="$CLIENT_TREE"
case_is "a forced dispatch publishes both clients"       0 "release upload \(call 1\): desktop-latest $ZIP $EXE $LNX --clobber" PUBLISHED_TREE="$CLIENT_TREE" PUBLISHED_LINUX_KEY="$LINUX_KEY" CLIENT_PUBLISH=force
case_is "notes that lose the Linux key fail the job"     1 'do not record the linux client key' EDIT_DROPS_LINUX_KEY=1

# The scrapes must not read each other'"'"'s line. Both labels are in the body and
# both keys are correct, so the ONLY way this run publishes a binary is if one
# pattern matched the other'"'"'s value — which is what a label like "Linux client
# source tree" would have done to the exe'"'"'s `.*Client source tree` pattern.
case_is "neither scrape reads the other label"           0 "release upload \(call 1\): desktop-latest $ZIP --clobber" PUBLISHED_TREE="$CLIENT_TREE" PUBLISHED_LINUX_KEY="$LINUX_KEY"

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
