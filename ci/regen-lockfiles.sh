#!/usr/bin/env bash
# Regenerates every committed MODULE.bazel.lock with the Bazel version in .bazelversion.
# With --check, fails instead when any of them is out of date and leaves them unchanged.
set -euo pipefail

usage() {
  echo "usage: ci/regen-lockfiles.sh [--check]" >&2
  exit 2
}

# Prefers a Bazel server without supplementary groups, which image builds in the same output base need.
run_bazel() {
  if sudo -n true 2>/dev/null; then
    "$root/ci/bin/group-free" bazel "$@"
  else
    bazel "$@"
  fi
}

# Runs `bazel mod deps`, which evaluates every module extension, unlike `bazel build --nobuild`.
process_lockfile() {
  local lockfile="$1"
  local actual
  echo "${action} ${lockfile}" >&2
  cd "$root/$(dirname "$lockfile")"
  actual="$(run_bazel --version)"
  if [[ "$actual" != "bazel $USE_BAZEL_VERSION" ]]; then
    echo "expected bazel $USE_BAZEL_VERSION, got: $actual" >&2
    exit 1
  fi
  run_bazel mod deps --lockfile_mode="$mode" >/dev/null
}

mode=update
action=Updating
case "$#:${1-}" in
  0:) ;;
  1:--check)
    mode=error
    action=Checking
    ;;
  *) usage ;;
esac

root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
USE_BAZEL_VERSION="$(<"$root/.bazelversion")"
export USE_BAZEL_VERSION

mapfile -t lockfiles < <(git -C "$root" ls-files -- '*MODULE.bazel.lock')
if [[ ${#lockfiles[@]} -eq 0 ]]; then
  echo "no committed MODULE.bazel.lock found" >&2
  exit 1
fi
for lockfile in "${lockfiles[@]}"; do
  (process_lockfile "$lockfile")
done
