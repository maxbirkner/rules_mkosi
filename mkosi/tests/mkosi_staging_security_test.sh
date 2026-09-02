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
    --mapping "$root/config" . tree \
    --mapping "$root/source" sub tree

ln -s "$root/outside/file" "$root/source/absolute"
expect_failure "$root/absolute" \
    --mapping "$root/config" . tree \
    --mapping "$root/source" src tree
rm "$root/source/absolute"

ln -s ../outside/file "$root/source/escape"
expect_failure "$root/escape" \
    --mapping "$root/config" . tree \
    --mapping "$root/source" src tree
rm "$root/source/escape"

for alias_target in "subdir/../file" "subdir//file" "./file" "subdir/" 'subdir\file'
do
    ln -s "$alias_target" "$root/source/noncanonical"
    expect_failure "$root/noncanonical" \
        --mapping "$root/config" . tree \
        --mapping "$root/source" src tree
    rm "$root/source/noncanonical"
done

mkdir "$root/source/subdir"
ln -s ../file "$root/source/subdir/sibling"
"$python" "$stage_script" --output "$root/canonical-parent" \
    --mapping "$root/config" . tree \
    --mapping "$root/source" src tree
test "$(readlink "$root/canonical-parent/src/subdir/sibling")" = ../file

ln -s sub/file "$root/config/alias"
expect_failure "$root/alias-prefix" \
    --mapping "$root/config" . tree \
    --mapping "$root/source" alias/child tree

ln -s "$root/config" "$root/config-alias"
expect_failure "$root/source-alias" \
    --mapping "$root/config" . tree \
    --mapping "$root/config-alias" src tree
