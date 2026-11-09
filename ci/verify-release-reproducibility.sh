#!/bin/bash
set -euo pipefail

workspace="$(pwd)"
USE_BAZEL_VERSION="$(<"$workspace/.bazelversion")"
export USE_BAZEL_VERSION
results="$workspace/.reproducibility-results"
make_removable() {
  if [[ -d "$1" ]]; then
    chmod -R u+w "$1"
  fi
}

cleanup() {
  for name in first second; do
    local output_root="$workspace/.reproducibility-output-$name"
    bazel --output_user_root="$output_root" shutdown \
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

# The two-stage subject reads its version from workspace status, like a stamped release.
workspace_status="$results/workspace-status.sh"
printf '#!/bin/sh\necho STABLE_RULES_MKOSI_TWO_STAGE_VERSION 1\n' >"$workspace_status"
chmod +x "$workspace_status"
targets=(
  //mkosi/tests:erofs_release_payload
  //mkosi/tests:erofs_release_reproducibility
  //mkosi/tests:release_reproducibility
  //mkosi/tests:two_stage_base
  //mkosi/tests:two_stage_input_version_reproducibility
  //mkosi/tests:two_stage_reproducibility
)

build_once() {
  local name="$1"
  local output_root="$workspace/.reproducibility-output-$name"
  make_removable "$output_root"
  rm -rf "$output_root"
  bazel \
    --output_user_root="$output_root" \
    build \
    --config=qualified \
    --lockfile_mode=error \
    --nouse_action_cache \
    --disk_cache="$output_root/action-cache" \
    --remote_cache= \
    --noremote_accept_cached \
    --noremote_upload_local_results \
    --workspace_status_command="$workspace_status" \
    --execution_log_json_file="$results/$name.execution.json" \
    "${targets[@]}"
  python3 ci/verify_reproducibility_execution.py \
    "$results/$name.execution.json" "$name"
  mkdir -p "$results/$name"
  local output
  while IFS= read -r output; do
    if [[ "$output" == *.json ]]; then
      cp "$output" "$results/$name/"
    elif [[ -d "$output" ]]; then
      # Update payloads are directories; compare the digest of every file.
      (cd "$(dirname "$output")" && find "$(basename "$output")" -type f -print0 | sort -z | xargs -0 sha256sum) \
        >>"$results/$name/base.sha256"
    else
      # The base archive and initrd are large; their digests suffice.
      (cd "$(dirname "$output")" && sha256sum "$(basename "$output")") >>"$results/$name/base.sha256"
    fi
  done < <(bazel \
    --output_user_root="$output_root" \
    cquery --lockfile_mode=error --output=files \
    "set(${targets[*]})")
}

build_once first
build_once second

if ! diff -ru "$results/first" "$results/second"; then
  echo "release reproducibility mismatch: immutable hashes or normalized manifests differ" >&2
  exit 1
fi
echo "independent release builds produced identical reproducibility manifests"
