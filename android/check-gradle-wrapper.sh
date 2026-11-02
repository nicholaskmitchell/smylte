#!/usr/bin/env bash
# Is gradle/wrapper/gradle-wrapper.jar the jar Gradle publishes for the version
# gradle-wrapper.properties names? CI runs `./gradlew`, which executes that jar
# before anything else, so a swapped jar would run arbitrary code with no other
# check standing in the way. The distribution the jar then downloads is pinned
# separately, by distributionSha256Sum in the same properties file, and the
# wrapper refuses a download that does not match it.
#
# The expected checksum is fetched from services.gradle.org, which is where
# Gradle publishes it. Run from anywhere.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
props="$here/gradle/wrapper/gradle-wrapper.properties"
jar="$here/gradle/wrapper/gradle-wrapper.jar"

version=$(sed -n 's#^distributionUrl=.*/gradle-\([0-9][0-9.]*\)-bin\.zip$#\1#p' "$props")
if [ -z "$version" ]; then
  echo "could not read the Gradle version from $props" >&2
  exit 1
fi
grep -q '^distributionSha256Sum=[0-9a-f]\{64\}$' "$props" || {
  echo "$props does not pin distributionSha256Sum" >&2
  exit 1
}

expected=$(curl -fsSL --retry 3 "https://services.gradle.org/distributions/gradle-${version}-wrapper.jar.sha256")
actual=$(sha256sum "$jar" | cut -d' ' -f1)
if [ "$expected" != "$actual" ]; then
  echo "gradle-wrapper.jar is not Gradle ${version}'s wrapper (expected $expected, got $actual)" >&2
  exit 1
fi
echo "gradle-wrapper.jar is Gradle ${version}'s ($actual)"
