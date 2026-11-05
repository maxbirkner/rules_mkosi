#!/bin/bash
# Builds the static Debian launcher, namespace runner, and Debian tools archive twice, each in a fresh output base
# with a different umask and no action, disk, or remote cache, and fails unless both builds executed every bootstrap
# action and produced identical files.
set -euo pipefail

workspace="$(pwd)"
USE_BAZEL_VERSION="$(<"$workspace/.bazelversion")"
export USE_BAZEL_VERSION
results="$workspace/.bootstrap-reproducibility"
targets=(
  @mkosi_debian_tools//:launcher
  @mkosi_debian_tools//:namespace_runner
  @mkosi_debian_tools//:tree
)

remove_output_bases() {
  local name
  for name in first second; do
    if [[ -d "$results/$name-output" ]]; then
      bazel --output_base="$results/$name-output" shutdown >/dev/null 2>&1 || true
      chmod -R u+w "$results/$name-output"
    fi
  done
  rm -rf "$results"
}
trap remove_output_bases EXIT

# Writes the digest and diagnostic text metadata of one bootstrap output to stdout.
describe_output() {
  local path="$1"
  sha256sum "$path" | cut -d' ' -f1
  stat --dereference --format='size %s, mode %a' "$path"
  case "$path" in
    *.tar) tar --list --verbose --numeric-owner --full-time --file="$path" ;;
    *) readelf --file-header --program-headers --notes "$path" ;;
  esac
}

build_once() {
  local name="$1"
  local mask="$2"
  local output_base="$results/$name-output"
  # Bazel 8 and 9 run every action with umask 022 whatever the server's umask is; the differing umasks keep the
  # check meaningful if a Bazel version or spawn strategy ever passes the server's umask through.
  (
    umask "$mask"
    bazel --output_base="$output_base" build \
      --config=deterministic \
      --nouse_action_cache \
      --remote_cache= \
      --execution_log_json_file="$results/$name.execution.json" \
      "${targets[@]}"
  )
  python3 ci/verify_reproducibility_execution.py "$results/$name.execution.json" "$name" bootstrap
  local execution_root
  execution_root="$(bazel --output_base="$output_base" info execution_root)"
  mkdir -p "$results/$name"
  local output
  while IFS= read -r output; do
    describe_output "$execution_root/$output" >"$results/$name/$(basename "$output").txt"
  done < <(bazel --output_base="$output_base" cquery --output=files "set(${targets[*]})")
}

rm -rf "$results"
mkdir -p "$results"
build_once first 0022
build_once second 0077

if ! diff -ru "$results/first" "$results/second"; then
  echo "bootstrap reproducibility mismatch: digests or metadata of the launcher, runner, or archive differ" >&2
  exit 1
fi
for description in "$results/first/"*.txt; do
  echo "$(basename "$description" .txt) SHA-256: $(head -n 1 "$description")"
done
echo "independent uncached builds produced identical Debian tools bootstrap outputs"
