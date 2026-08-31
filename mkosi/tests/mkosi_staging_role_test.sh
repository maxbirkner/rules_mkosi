#!/bin/sh
set -eu

python="$1"
stage_script="$2"
output="$TEST_TMPDIR/role"

for source in "$3" "$4"; do
    if "$python" "$stage_script" \
        --output "$output" \
        --mapping "$source" src tree; then
        echo "a source-tree mapping accepted a regular file: $source" >&2
        exit 1
    fi
    test ! -e "$output"
done
