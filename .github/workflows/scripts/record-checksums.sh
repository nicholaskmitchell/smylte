#!/usr/bin/env bash
# Writes the SHA-256 of every file on `desktop-latest` into its notes, then asks
# the GitLab sync to copy the release over now rather than at its next run.
#
# The desktop clients read the release from GitLab first (Updater.cs). GitLab's
# copy links to the files on GitHub but carries none of GitHub's per-file
# metadata, so these lines are how a client reading it tells builds apart and
# checks what it downloaded. A client that finds no checksums on GitLab, or a
# download that does not match them, asks GitHub instead, so every failure here
# costs a GitHub request rather than an update.
#
# Run by desktop-release.yml after "Publish the rolling release", from the
# repository root, with GH_TOKEN and GITHUB_REPOSITORY set. Tested by
# .github/workflows/tests/record-checksums.test.sh against a stub `gh`.
set -euo pipefail

# The heading the block starts with. Everything from it to the end of the notes
# is this script's, and is rewritten on every run.
HEADING="Checksums (the desktop clients check each download against these):"

retry() {
  local attempt=1 max=5 delay=5 what="$1 ${2:-} ${3:-}"
  until "$@"; do
    if [ "$attempt" -ge "$max" ]; then
      echo "::error::\`$what\` failed $max times; giving up" >&2
      return 1
    fi
    echo "::warning::\`$what\` failed (attempt $attempt/$max); retrying in ${delay}s" >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

# Prints only on success: on an HTTP error `gh api` writes the error body to
# stdout, which `$(retry ...)` would otherwise capture (see desktop-release.yml).
release_json() {
  local json
  json=$(gh api "repos/${GITHUB_REPOSITORY}/releases/tags/desktop-latest") || return 1
  printf '%s\n' "$json"
}

JSON=$(retry release_json)

# The notes as they stand, less any block a previous run wrote, and one line per
# file whose digest GitHub states, sorted so an unchanged release writes
# unchanged notes.
read_release() {
  python3 -c '
import json, sys
heading, part = sys.argv[1], sys.argv[2]
release = json.load(sys.stdin)
if part == "body":
    body = (release.get("body") or "").replace("\r\n", "\n")
    lines = body.split("\n")
    if heading in lines:
        lines = lines[: lines.index(heading)]
    print("\n".join(lines).rstrip())
else:
    sums = sorted(
        "- " + a["name"] + ": " + a["digest"].lower()
        for a in release.get("assets") or []
        if isinstance(a.get("digest"), str) and a["digest"].lower().startswith("sha256:")
    )
    print("\n".join(sums))
' "$HEADING" "$1"
}
BASE=$(read_release body <<<"$JSON")
SUMS=$(read_release sums <<<"$JSON")

if ! grep -q '^- smylte-web.zip: sha256:' <<<"$SUMS"; then
  # Not a failure of the publish: the clients go to GitHub for the release.
  echo "::warning::GitHub states no digest for smylte-web.zip; no checksums written, so clients will read the release from GitHub" >&2
else
  NOTES="${BASE}

${HEADING}
${SUMS}"
  retry gh release edit desktop-latest --notes "$NOTES"

  # Read back, as the publish step does: notes that lost the block would send
  # every client to GitHub, which works but is not what this run is for.
  BODY=$(retry release_json | python3 -c 'import json, sys; print(json.load(sys.stdin).get("body") or "")')
  while IFS= read -r line; do
    if ! grep -qxF -- "$line" <<<"$BODY"; then
      echo "::error::desktop-latest notes do not record '${line}'" >&2
      exit 1
    fi
  done <<<"$SUMS"
  echo "Recorded $(wc -l <<<"$SUMS") checksum(s) on desktop-latest"
fi

# GitHub does not start workflows for a release edited with the job's own token,
# so the sync would otherwise copy the release at its next run (a GitLab event,
# or the daily schedule). Until it does, GitLab's copy describes the previous
# files and clients that read it fall back to GitHub, so a failure to start it
# is a warning.
if gh workflow run sync-issues.yml --ref main >/dev/null; then
  echo "Started the GitLab sync"
else
  echo "::warning::could not start sync-issues.yml; GitLab's copy of the release updates at the sync's next run" >&2
fi
