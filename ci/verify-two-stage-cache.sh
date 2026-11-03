#!/bin/bash
# Builds //mkosi/tests:two_stage_release for two stamped versions in one output
# base and checks that the second version reuses the cached mkosi_base.
set -euo pipefail

workspace="$(pwd)"
results="$workspace/.two-stage-cache-results"
output_root="$workspace/.two-stage-cache-output"
make_removable() {
  if [[ -d "$1" ]]; then
    chmod -R u+w "$1"
  fi
}

cleanup() {
  USE_BAZEL_VERSION=8.5.1 bazel --output_user_root="$output_root" shutdown \
    >/dev/null 2>&1 || true
  make_removable "$output_root"
  rm -rf "$output_root" "$results"
}
trap cleanup EXIT

make_removable "$output_root"
rm -rf "$output_root" "$results"
mkdir -p "$results"

build_version() {
  local version="$1"
  local status="$results/workspace-status-$version.sh"
  printf '#!/bin/sh\necho STABLE_RULES_MKOSI_TWO_STAGE_VERSION %s\n' "$version" >"$status"
  chmod +x "$status"
  USE_BAZEL_VERSION=8.5.1 bazel \
    --output_user_root="$output_root" \
    build \
    --config=qualified \
    --lockfile_mode=error \
    --disk_cache= \
    --remote_cache= \
    --workspace_status_command="$status" \
    --execution_log_json_file="$results/$version.execution.json" \
    //mkosi/tests:two_stage_release
  local metadata
  metadata="$(USE_BAZEL_VERSION=8.5.1 bazel \
    --output_user_root="$output_root" \
    cquery --lockfile_mode=error --output=files \
    //mkosi/tests:two_stage_release 2>/dev/null | grep -F '.mkosi-image-info.json')"
  python3 - "$metadata" "$version" <<'PY'
import json
import sys

image = json.load(open(sys.argv[1], encoding="utf-8"))["image"]
if image != {"id": "rules-mkosi-ab", "version": sys.argv[2]}:
    raise SystemExit("unexpected image identity {}".format(image))
PY
}

build_version 1
build_version 2
python3 ci/verify_two_stage_cache.py "$results/1.execution.json" "$results/2.execution.json"
