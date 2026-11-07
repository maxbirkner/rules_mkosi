#!/usr/bin/env bash
# Runs the BCR presubmit's test-module targets under the limits of a stock BCR runner: from a source archive of HEAD,
# with a Bazel server that keeps its supplementary groups, without a repository cache, and with snapshot.debian.org
# blocked.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: bcr-presubmit.sh WORK_DIR [BAZEL_TEST_FLAG...]" >&2
  exit 2
fi

work="$1"
shift
mkdir -p "$work"
work="$(realpath "$work")"
git archive --format=tar --prefix=source/ HEAD | tar -x -C "$work"
printf 'block snapshot.debian.org\n' >"$work/downloader.cfg"

cd "$work/source/e2e/smoke"
bazel test --repository_cache= --disk_cache= --downloader_config="$work/downloader.cfg" "$@" //:stock_runner_tests
