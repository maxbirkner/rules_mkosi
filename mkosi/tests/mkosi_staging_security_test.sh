#!/bin/sh
set -eu

python="$1"
stage_script="$2"
root="$TEST_TMPDIR/staging-security"
rm -rf "$root"
mkdir -p "$root/config/sub" "$root/source" "$root/outside"
printf config > "$root/config/sub/file"
printf source > "$root/source/file"
printf outside > "$root/outside/file"

expect_failure() {
    output="$1"
    shift
    if "$python" "$stage_script" --output "$output" "$@"; then
        echo "staging unexpectedly succeeded" >&2
        exit 1
    fi
    test ! -e "$output"
}

# A source destination may not replace or sit below any config-tree entry.
expect_failure "$root/exact" \
    --mapping "$root/config" . \
    --mapping "$root/source" sub

ln -s "$root/outside/file" "$root/source/absolute"
expect_failure "$root/absolute" \
    --mapping "$root/config" . \
    --mapping "$root/source" src
rm "$root/source/absolute"

ln -s ../outside/file "$root/source/escape"
expect_failure "$root/escape" \
    --mapping "$root/config" . \
    --mapping "$root/source" src
rm "$root/source/escape"

ln -s sub/file "$root/config/alias"
expect_failure "$root/alias-prefix" \
    --mapping "$root/config" . \
    --mapping "$root/source" alias/child

ln -s "$root/config" "$root/config-alias"
expect_failure "$root/source-alias" \
    --mapping "$root/config" . \
    --mapping "$root/config-alias" src
