#!/bin/bash
set -euo pipefail

python="$1"
stage_script="$2"
config_tree="$3"
source_tree="$4"
output="$TEST_TMPDIR/staged"

"$python" "$stage_script" \
    --output "$output" \
    --mapping "$config_tree" . tree \
    --mapping "$source_tree" src tree

test -f "$output/mkosi.conf"
test -f "$output/mkosi.conf.d/20-extra.conf"
test -f "$output/mkosi.extra/etc/declared-marker"
test -f "$output/src/hello.txt"
test "$(cat "$output/mkosi.extra/etc/declared-marker")" = "declared extra"
