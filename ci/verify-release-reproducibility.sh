#!/bin/bash
set -euo pipefail

workspace="$(pwd)"
results="$workspace/.reproducibility-results"
make_removable() {
  if [[ -d "$1" ]]; then
    chmod -R u+w "$1"
  fi
}

cleanup() {
  for name in first second; do
    local output_root="$workspace/.reproducibility-output-$name"
    USE_BAZEL_VERSION=8.5.1 bazel --output_user_root="$output_root" shutdown \
      >/dev/null 2>&1 || true
    make_removable "$output_root"
    rm -rf "$output_root"
  done
  rm -rf "$results"
}
trap cleanup EXIT

make_removable "$results"
rm -rf "$results"
mkdir -p "$results"

build_once() {
  local name="$1"
  local output_root="$workspace/.reproducibility-output-$name"
  make_removable "$output_root"
  rm -rf "$output_root"
  USE_BAZEL_VERSION=8.5.1 bazel \
    --output_user_root="$output_root" \
    build \
    --config=qualified \
    --lockfile_mode=error \
    --disk_cache= \
    --remote_cache= \
    --noremote_accept_cached \
    --noremote_upload_local_results \
    //mkosi/tests:release_reproducibility
  local output
  output="$(USE_BAZEL_VERSION=8.5.1 bazel \
    --output_user_root="$output_root" \
    cquery --lockfile_mode=error --output=files \
    //mkosi/tests:release_reproducibility)"
  cp "$output" "$results/$name.json"
}

build_once first
build_once second

if ! diff -u "$results/first.json" "$results/second.json"; then
  echo "release reproducibility mismatch: immutable hashes or normalized manifests differ" >&2
  exit 1
fi
echo "independent release builds produced identical reproducibility manifests"
