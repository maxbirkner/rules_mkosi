#!/usr/bin/env bash
set -euo pipefail

help="$(
  {
    bazel help startup_options
    bazel help coverage
  } 2>&1
)"

if grep -Fq -- "--starlark_coverage_report" <<<"$help"; then
  echo "Bazel now advertises Starlark coverage; repeat the empirical probe in docs/starlark-coverage.md." >&2
  exit 1
fi

echo "$(bazel --version) does not advertise --starlark_coverage_report"
