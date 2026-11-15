# shellcheck shell=sh
# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
# Qualifies the host for foreign-architecture image builds: the runner registers the pinned arm64 emulator in a
# binfmt_misc instance private to its user namespace, runs an arm64 program through it, and runs a command with the
# caller's own identity.
runner="$(rlocation "$1")"
emulator="$(rlocation "$2")"

"$runner" --check --architecture arm64 --emulator "$emulator"

expected="$(id -u):$(id -g)"
# shellcheck disable=SC2016 # The inner shell expands the identity.
actual="$("$runner" --architecture arm64 --emulator "$emulator" -- sh -c 'echo "$(id -u):$(id -g)"')"
if [ "$actual" != "$expected" ]; then
  echo "FAIL binfmt_misc: the command ran as $actual instead of $expected" >&2
  exit 1
fi
echo "PASS binfmt_misc: the command ran with the caller's identity $expected"

set +e
"$runner" --architecture arm64 --emulator "$emulator" -- sh -c 'exit 7'
status=$?
set -e
if [ "$status" -ne 7 ]; then
  echo "FAIL binfmt_misc: the runner returned $status instead of the command's status 7" >&2
  exit 1
fi
echo "PASS binfmt_misc: the runner returns the command's exit status"
