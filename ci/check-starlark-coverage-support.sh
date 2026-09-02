#!/usr/bin/env bash
set -euo pipefail

umask 077
scratch_parent="$(cd "$PWD/.." && pwd)"
scratch_base="$scratch_parent/.starlark-coverage-probe-${BASHPID}-${RANDOM}"
scratch="$scratch_base"
attempt=0
while ! mkdir "$scratch" 2>/dev/null; do
  ((attempt += 1))
  scratch="${scratch_base}-${attempt}"
done

probe="$scratch/module"
output_user_root="$scratch/output-user-root"
reports="$scratch/reports"
flag_report="$reports/starlark-coverage.lcov"
bazel_startup=(
  --ignore_all_rc_files
  "--output_user_root=$output_user_root"
)

cleanup() {
  bazel "${bazel_startup[@]}" shutdown >/dev/null 2>&1 || true
  chmod -R u+w "$scratch" 2>/dev/null || true
  rm -rf "$scratch"
}
trap cleanup EXIT

mkdir "$probe" "$reports"
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

version="$(bazel "${bazel_startup[@]}" version 2>/dev/null | awk '/Build label:/ { print "bazel " $3 }')"
if [[ -n "${USE_BAZEL_VERSION:-}" && "$version" != "bazel $USE_BAZEL_VERSION" ]]; then
  echo "expected bazel $USE_BAZEL_VERSION, got $version" >&2
  exit 1
fi

(
  cd "$probe"
  bazel "${bazel_startup[@]}" coverage --lockfile_mode=off \
    --combined_report=lcov //:probe
)
combined_report="$(
  cd "$probe"
  bazel "${bazel_startup[@]}" info --lockfile_mode=off output_path
)/_coverage/_coverage_report.dat"

help="$(
  {
    bazel "${bazel_startup[@]}" help startup_options
    bazel "${bazel_startup[@]}" help coverage
  } 2>&1
)"

candidate_report=
if grep -Fq -- "--starlark_coverage_report" <<<"$help"; then
  rm -rf "$reports"
  mkdir "$reports"
  (
    cd "$probe"
    bazel "${bazel_startup[@]}" test --lockfile_mode=off \
      --starlark_coverage_report="$flag_report" //:probe
  ) || {
    echo "advertised --starlark_coverage_report failed; resume issue #26" >&2
    exit 1
  }
  if [[ ! -f "$flag_report" ]]; then
    echo "advertised --starlark_coverage_report created no fresh report; resume issue #26" >&2
    exit 1
  fi
  candidate_report="$flag_report"
fi

meaningful_report=
for report in "$combined_report" ${candidate_report:+"$candidate_report"}; do
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
