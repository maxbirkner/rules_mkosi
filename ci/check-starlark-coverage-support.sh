#!/usr/bin/env bash
set -euo pipefail

probe=issue26_starlark_coverage_probe
flag_report="$PWD/starlark-coverage-capability.lcov"

cleanup() {
  rm -rf "$probe"
  rm -f "$flag_report"
}
trap cleanup EXIT

mkdir "$probe"
cat >"$probe/MODULE.bazel" <<'EOF'
module(name = "starlark_coverage_probe")
EOF
cat >"$probe/BUILD.bazel" <<'EOF'
load(":probe.bzl", "probe_test")

probe_test(name = "probe")
EOF
cat >"$probe/probe.bzl" <<'EOF'
def _probe_test_impl(ctx):
    out = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(out, "#!/bin/sh\nexit 0\n", is_executable = True)
    if ctx.attr.covered:
        marker = "executed"
    else:
        marker = "unexecuted"
    _ignore = marker
    return [DefaultInfo(executable = out)]

probe_test = rule(
    implementation = _probe_test_impl,
    test = True,
    attrs = {"covered": attr.bool(default = True)},
)
EOF

(
  cd "$probe"
  bazel coverage --lockfile_mode=off --combined_report=lcov //:probe
)
combined_report="$(
  cd "$probe"
  bazel info --lockfile_mode=off output_path
)/_coverage/_coverage_report.dat"

help="$(
  {
    bazel help startup_options
    bazel help coverage
  } 2>&1
)"

if grep -Fq -- "--starlark_coverage_report" <<<"$help"; then
  (
    cd "$probe"
    bazel test --lockfile_mode=off \
      --starlark_coverage_report="$flag_report" //:probe
  )
fi

meaningful_report=
for report in "$combined_report" "$flag_report"; do
  if [[ -s "$report" ]] && awk -v source="probe.bzl" '
    $0 == "SF:" source { in_source = 1; next }
    in_source && /^SF:/ { in_source = 0 }
    in_source && /^DA:[0-9]+,0$/ { uncovered = 1 }
    in_source && /^DA:[0-9]+,[1-9][0-9]*$/ { covered = 1 }
    END { exit !(covered && uncovered) }
  ' "$report"; then
    meaningful_report="$report"
    break
  fi
done

version="$(bazel --version)"
if [[ -n "$meaningful_report" ]]; then
  message="$version produced meaningful executed and unexecuted .bzl LCOV in $meaningful_report; resume issue #26"
  echo "$message" >&2
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf '## Starlark coverage capability detected\n\n%s\n' "$message" \
      >>"$GITHUB_STEP_SUMMARY"
  fi
  exit 1
fi

message="$version remains unsupported: no real LCOV report distinguishes executed and unexecuted .bzl lines"
echo "$message"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  printf '## Starlark coverage remains unsupported\n\n%s\n' "$message" \
    >>"$GITHUB_STEP_SUMMARY"
fi
