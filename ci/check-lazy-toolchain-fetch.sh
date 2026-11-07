#!/bin/bash
# Analyses targets that use no rules_mkosi toolchain in a fresh output base and fails if Bazel fetched a repository
# that only an mkosi, QEMU, Debian tools, or static bootstrap C/C++ toolchain needs, such as the LLVM toolchain and the
# musl runtime sources of the llvm module. Toolchain resolution loads every registered toolchain, so the repositories
# that declare them must download nothing. Unless --consumer-uses-llvm is given, the llvm module itself must not be
# fetched either; with it, for a consumer that registers the llvm module's toolchains itself, only the musl runtime
# sources count as the static bootstrap toolchain's.
#
# With --consumer-cc-target, also fails if that C/C++ target of the consumer fetches the musl runtime of the static
# bootstrap toolchain or, unless --consumer-uses-llvm is given, resolves the llvm module's toolchain or fetches any of
# its repositories. With --bootstrap-target, also fails unless that target, which builds a bootstrap executable, and
# the execution tools that it needs resolve only the llvm module's toolchain and fetch its musl runtime, which shows
# that the checks above can detect it.
#
# Usage: ci/check-lazy-toolchain-fetch.sh [--consumer-uses-llvm] [--consumer-cc-target LABEL]
#   [--bootstrap-target LABEL] MODULE_DIR TARGET...
# LOCKFILE_MODE, when set, is passed as --lockfile_mode.
set -euo pipefail
shopt -s nullglob

consumer_cc_target=""
bootstrap_target=""
consumer_uses_llvm=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --consumer-uses-llvm) consumer_uses_llvm=true; shift ;;
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
# The llvm module, whose C/C++ toolchain the static bootstrap executables use, and its musl runtime sources, which only
# rules_mkosi's static bootstrap toolchain needs unless the consumer builds musl targets itself.
llvm_module=llvm
musl_runtime=musl_libc
llvm_cc_toolchain="$llvm_module+//toolchain:linux_x86_64_cc_toolchain"
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
  "$musl_runtime"
)
# A consumer's own registration of the llvm module's toolchains may load the LLVM sources and fetch the compiler.
if [[ "$consumer_uses_llvm" == false ]]; then
  heavy+=(llvm-project llvm-toolchain-minimal-linux-amd64 toolchain-extra-prebuilts-linux-amd64)
fi
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

# Succeeds if the llvm module or any repository of its module extensions was fetched.
was_llvm_fetched() {
  grep -q -- "^$llvm_module+" <<<"$(list_fetched)"
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
  if [[ "$consumer_uses_llvm" == false ]] && was_llvm_fetched; then
    echo "the $llvm_module module was fetched for targets that use no rules_mkosi toolchain" >&2
    status=1
  fi
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

# Fails if the consumer's C/C++ target fetches the musl runtime or, unless the consumer uses the llvm module itself,
# resolves its toolchain or fetches any of its repositories.
check_consumer_cc_target() {
  local selected
  selected="$(list_selected_cc_toolchains "$1")" || return 1
  echo "C/C++ toolchains selected for $1:" "$selected"
  if [[ -z "$selected" ]]; then
    echo "$1 resolved no C/C++ toolchain" >&2
    return 1
  fi
  if [[ "$consumer_uses_llvm" == false ]] && grep -qF -- "$llvm_cc_toolchain" <<<"$selected"; then
    echo "$1 resolved rules_mkosi's static bootstrap toolchain instead of the consumer's own" >&2
    return 1
  fi
  if was_fetched "$musl_runtime"; then
    echo "@$musl_runtime was fetched for $1" >&2
    return 1
  fi
  if [[ "$consumer_uses_llvm" == false ]] && was_llvm_fetched; then
    echo "the $llvm_module module was fetched for $1" >&2
    return 1
  fi
}

# Fails unless the bootstrap executable, including the execution tools that it needs, resolves only the llvm module's
# toolchain and fetches its musl runtime.
check_bootstrap_target() {
  local selected
  selected="$(list_selected_cc_toolchains "$1")" || return 1
  echo "C/C++ toolchains selected for $1:" "$selected"
  if ! grep -qF -- "$llvm_cc_toolchain" <<<"$selected"; then
    echo "$1 did not resolve rules_mkosi's static bootstrap toolchain" >&2
    return 1
  fi
  if grep -vF -- "$llvm_cc_toolchain" <<<"$selected"; then
    echo "$1 resolved the C/C++ toolchains above besides rules_mkosi's static bootstrap toolchain" >&2
    return 1
  fi
  if ! was_fetched "$musl_runtime"; then
    echo "@$musl_runtime was not fetched for $1" >&2
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
  echo "$consumer_cc_target resolved the consumer's C/C++ toolchain without fetching @$musl_runtime"
fi
if [[ -n "$bootstrap_target" ]]; then
  check_bootstrap_target "$bootstrap_target" || report_failure
  echo "$bootstrap_target resolved the static bootstrap toolchain and fetched @$musl_runtime"
fi
