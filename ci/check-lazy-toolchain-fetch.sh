#!/bin/bash
# Analyses targets that use no rules_mkosi toolchain in a fresh output base and
# fails if Bazel fetched a repository that only an mkosi, QEMU, or Debian tools
# toolchain needs. Toolchain resolution loads every registered toolchain, so the
# repositories that declare them must download nothing.
#
# Usage: ci/check-lazy-toolchain-fetch.sh MODULE_DIR TARGET...
# LOCKFILE_MODE, when set, is passed as --lockfile_mode.
set -euo pipefail

module="$(cd -- "${1:?module directory is required}" && pwd)"
shift
[[ $# -gt 0 ]] || { echo "at least one target is required" >&2; exit 2; }
bazel_command="${BAZEL:-bazel}"
output_base="$module/.cache/lazy-toolchain-fetch"

# Registering the toolchains must fetch these lightweight repositories.
declarations=(mkosi_toolchains mkosi_debian_tools)
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
)

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
(cd "$module" && "$bazel_command" --output_base="$output_base" build --nobuild "${flags[@]}" "$@")

# Canonical names of fetched repositories, without the marker file decoration.
fetched=()
for entry in "$output_base"/external/*; do
  name="${entry##*/}"
  name="${name#@}"
  fetched+=("${name%.marker}")
done

was_fetched() {
  local name
  for name in "${fetched[@]}"; do
    [[ "$name" == *"+$1" ]] && return 0
  done
  return 1
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

status=0
for repository in "${declarations[@]}"; do
  canonical=""
  for name in "${fetched[@]}"; do
    if [[ "$name" == *"+$repository" && -d "$output_base/external/$name" ]]; then
      canonical="$name"
    fi
  done
  if [[ -z "$canonical" ]]; then
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
if [[ $status -ne 0 ]]; then
  printf 'fetched repositories:\n' >&2
  printf '  %s\n' "${fetched[@]}" | sort -u >&2
  exit 1
fi
echo "No rules_mkosi toolchain repository beyond the declarations was fetched for: $*"
