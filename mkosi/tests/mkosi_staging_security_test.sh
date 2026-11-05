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

# Assembling a configuration tree shares sources and merges directories, but still rejects colliding files.
"$python" "$stage_script" --merge --output "$root/merged" \
    --mapping "$root/config" . tree \
    --mapping "$root/source/file" sub/other file \
    --mapping "$root/source" shared/one tree \
    --mapping "$root/source" shared/two tree \
    --executable shared/two/file
test "$(cat "$root/merged/sub/file")" = config
test "$(cat "$root/merged/sub/other")" = source
test "$(cat "$root/merged/shared/one/file")" = source
test "$(stat -c %a "$root/merged/shared/two/file")" = 755
test "$(stat -c %a "$root/merged/shared/one/file")" = 644

expect_failure "$root/merged-file" --merge \
    --mapping "$root/config" . tree \
    --mapping "$root/source/file" sub/file file

expect_failure "$root/merged-file-directory" --merge \
    --mapping "$root/config" . tree \
    --mapping "$root/source/file" sub file

# A merged directory belongs to every tree that contributes it, in either mapping order.
mkdir -p "$root/merged-usr-a/usr/lib" "$root/merged-usr-b/usr/lib" "$root/merged-usr-a/only-a"
printf a > "$root/merged-usr-a/usr/lib/a"
printf b > "$root/merged-usr-b/usr/lib/b"
ln -s usr/lib "$root/merged-usr-b/lib"
stage_merged_usr() {
    "$python" "$stage_script" --merge --output "$root/merged-usr-$1$2" \
        --mapping "$root/merged-usr-$1" . tree \
        --mapping "$root/merged-usr-$2" . tree
    test "$(readlink "$root/merged-usr-$1$2/lib")" = usr/lib
    test "$(cat "$root/merged-usr-$1$2/usr/lib/b")" = b
}
stage_merged_usr a b
stage_merged_usr b a

# A link may still not point to a directory that only another tree contributes.
ln -s only-a "$root/merged-usr-b/alias"
expect_failure "$root/merged-alias" --merge \
    --mapping "$root/merged-usr-a" . tree \
    --mapping "$root/merged-usr-b" . tree
rm "$root/merged-usr-b/alias"

# Source files are checked behind Bazel's sandbox and execroot links, whose targets end with the path they stand for.
python_path="$(realpath "$python")"
stage_path="$(realpath "$stage_script")"
mkdir -p "$root/workspace/pkg/sub" "$root/execroot" "$root/sandbox"
printf regular > "$root/workspace/pkg/file"
ln -s file "$root/workspace/pkg/relative"
ln -s "$root/outside/file" "$root/workspace/pkg/absolute"
ln -s "$root/outside" "$root/workspace/pkg/linked"
ln -s "$root/workspace/pkg" "$root/execroot/pkg"
stage_source() {
    mkdir -p "$root/sandbox/pkg/$(dirname "$1")"
    ln -sfn "$root/execroot/pkg/$1" "$root/sandbox/pkg/$1"
    (cd "$root/sandbox" && "$python_path" "$stage_path" --merge --output "$root/source-$2" \
        --source-file "pkg/$1" "$1" pkg 2> "$root/source-$2.err")
}
stage_source file regular
test "$(cat "$root/source-regular/file")" = regular
for name in relative absolute linked/file; do
    if stage_source "$name" rejected; then
        echo "a symlinked source file was staged: $name" >&2
        exit 1
    fi
    grep -q "is a symlink or lies below one at pkg/${name%%/*};" "$root/source-rejected.err"
    test ! -e "$root/source-rejected"
done
if stage_source sub directory; then
    echo "a source directory was staged as a file" >&2
    exit 1
fi
grep -q "is a directory; map it through trees with mkosi_config_tree(src = ...)" "$root/source-directory.err"
