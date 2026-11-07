#!/bin/bash
# Analyses targets that use no rules_mkosi toolchain in a fresh output base and fails if Bazel fetched a repository
# that only an mkosi, QEMU, Debian tools, or static bootstrap C/C++ toolchain needs, such as the zig SDK. Toolchain
# resolution loads every registered toolchain, so the repositories that declare them must download nothing.
#
# With --consumer-cc-target, also fails if that C/C++ target of the consumer resolves the zig toolchain or fetches the
# zig SDK. With --bootstrap-target, also fails unless that target, which builds a bootstrap executable, resolves the
# zig toolchain and fetches the zig SDK, which shows that the checks above can detect it.
#
# Usage: ci/check-lazy-toolchain-fetch.sh [--consumer-cc-target LABEL] [--bootstrap-target LABEL] MODULE_DIR TARGET...
# LOCKFILE_MODE, when set, is passed as --lockfile_mode.
set -euo pipefail
shopt -s nullglob

consumer_cc_target=""
bootstrap_target=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --consumer-cc-target) consumer_cc_target="${2:?--consumer-cc-target needs a label}"; shift 2 ;;
    --bootstrap-target) bootstrap_target="${2:?--bootstrap-target needs a label}"; shift 2 ;;
    *) break ;;
  esac
done
module="$(cd -- "${1:?module directory is required}" && pwd)"
shift
[[ $# -gt 0 ]] || { echo "at least one target is required" >&2; exit 2; }
bazel_command="${BAZEL:-bazel}"
output_base="$module/.cache/lazy-toolchain-fetch"

# Registering the toolchains must fetch these lightweight repositories.
declarations=(mkosi_toolchains mkosi_debian_tools)
# The zig SDK, which only the static bootstrap C/C++ toolchain needs.
zig_sdk=zig_config
# Only the selected toolchains may fetch these.
heavy=(
  mkosi_source
  mkosi_ovmf
  mkosi_seabios
  mkosi_debian_package_inputs
  mkosi_debian_python
  mkosi_debian_snapshot
  qemu_img_prebuilt_linux_amd64
  qemu_system_bin_prebuilt_linux_amd64_x86_64_softmmu
  qemu_system_data_prebuilt_linux_amd64
  "$zig_sdk"
)
cc_toolchain_type="@bazel_tools//tools/cpp:toolchain_type"

remove_output_base() {
  if [[ -d "$output_base" ]]; then
    "$bazel_command" --output_base="$output_base" shutdown >/dev/null 2>&1 || true
    chmod -R u+w "$output_base"
    rm -rf "$output_base"
  fi
}
trap remove_output_base EXIT
remove_output_base

flags=()
if [[ -n "${LOCKFILE_MODE:-}" ]]; then
  flags+=(--lockfile_mode="$LOCKFILE_MODE")
fi

run_bazel() {
  (cd "$module" && "$bazel_command" --output_base="$output_base" "$@")
}

# Prints the canonical names of the fetched repositories, without the marker file decoration.
list_fetched() {
  local entry name
  for entry in "$output_base"/external/*; do
    name="${entry##*/}"
    name="${name#@}"
    echo "${name%.marker}"
  done | sort -u
}

was_fetched() {
  grep -q -- "+$1\$" <<<"$(list_fetched)"
}

# Fails unless the repository holds only a few generated files, such as BUILD.bazel, and nothing it downloaded.
check_declarations() {
  local repository="$1" path="$output_base/external/$2" others size
  others="$(find -L "$path" -mindepth 1 ! -type f)"
  if [[ -n "$others" ]]; then
    echo "@$repository holds more than generated files:" >&2
    head -n 5 <<<"$others" >&2
    return 1
  fi
  size="$(du -sLk "$path" | cut -f1)"
  if [[ $size -gt 64 ]]; then
    echo "@$repository holds $size KiB, more than the declarations need" >&2
    return 1
  fi
}

# Fails unless the repositories that declare toolchains, and none of the heavy ones, were fetched.
check_lazy_fetch() {
  local status=0 repository canonical
  for repository in "${declarations[@]}"; do
    canonical="$(grep -- "+$repository\$" <<<"$(list_fetched)" | tail -n 1 || true)"
    if [[ -z "$canonical" || ! -d "$output_base/external/$canonical" ]]; then
      echo "expected the toolchain declarations in @$repository to be fetched" >&2
      status=1
    elif ! check_declarations "$repository" "$canonical"; then
      status=1
    fi
  done
  for repository in "${heavy[@]}"; do
    if was_fetched "$repository"; then
      echo "@$repository was fetched for targets that use no rules_mkosi toolchain" >&2
      status=1
    fi
  done
  return "$status"
}

# Prints the C/C++ toolchains that Bazel selects while analysing the given target.
list_selected_cc_toolchains() {
  local log
  if ! log="$(run_bazel cquery "${flags[@]}" --toolchain_resolution_debug="$cc_toolchain_type" "$1" 2>&1 >/dev/null)"; then
    echo "$log" >&2
    return 1
  fi
  sed -n "s|.*type @*${cc_toolchain_type} -> toolchain \(.*\)\$|\1|p" <<<"$log" | sort -u
}

# Fails if the consumer's C/C++ target resolves the zig toolchain or fetches the zig SDK.
check_consumer_cc_target() {
  local selected
  selected="$(list_selected_cc_toolchains "$1")" || return 1
  echo "C/C++ toolchains selected for $1:" "$selected"
  if [[ -z "$selected" ]]; then
    echo "$1 resolved no C/C++ toolchain" >&2
    return 1
  fi
  if grep -q -- "+$zig_sdk//" <<<"$selected"; then
    echo "$1 resolved rules_mkosi's static bootstrap toolchain instead of the consumer's own" >&2
    return 1
  fi
  if was_fetched "$zig_sdk"; then
    echo "@$zig_sdk was fetched for $1" >&2
    return 1
  fi
}

# Fails unless the bootstrap executable resolves the zig toolchain and fetches the zig SDK.
check_bootstrap_target() {
  local selected
  selected="$(list_selected_cc_toolchains "$1")" || return 1
  echo "C/C++ toolchains selected for $1:" "$selected"
  if ! grep -q -- "+$zig_sdk//" <<<"$selected"; then
    echo "$1 did not resolve rules_mkosi's static bootstrap toolchain" >&2
    return 1
  fi
  if ! was_fetched "$zig_sdk"; then
    echo "@$zig_sdk was not fetched for $1" >&2
    return 1
  fi
}

report_failure() {
  printf 'fetched repositories:\n' >&2
  list_fetched | sed 's/^/  /' >&2
  exit 1
}

run_bazel build --nobuild "${flags[@]}" "$@"
check_lazy_fetch || report_failure
echo "No rules_mkosi toolchain repository beyond the declarations was fetched for: $*"
if [[ -n "$consumer_cc_target" ]]; then
  check_consumer_cc_target "$consumer_cc_target" || report_failure
  echo "$consumer_cc_target resolved the consumer's C/C++ toolchain without fetching @$zig_sdk"
fi
if [[ -n "$bootstrap_target" ]]; then
  check_bootstrap_target "$bootstrap_target" || report_failure
  echo "$bootstrap_target resolved the static bootstrap toolchain and fetched @$zig_sdk"
fi
