#!/bin/bash
set -euo pipefail

python="$1"
stage_script="$2"
config_tree="$3"
source_tree="$4"
payload_tree="$5"
output="$TEST_TMPDIR/staged"

"$python" "$stage_script" \
    --output "$output" \
    --mapping "$config_tree" . tree \
    --mapping "$source_tree" src tree \
    --mapping "$payload_tree" mkosi.extra/payload-root tree \
    --executable mkosi.extra/payload-root/usr/local/bin/example

test -f "$output/mkosi.conf"
test -f "$output/mkosi.conf.d/20-extra.conf"
test -f "$output/mkosi.extra/etc/declared-marker"
test -f "$output/src/hello.txt"
test "$(cat "$output/mkosi.extra/etc/declared-marker")" = "declared extra"
test -x "$output/mkosi.extra/payload-root/usr/local/bin/example"
test -L "$output/mkosi.extra/payload-root/usr/local/bin/example-link"
test "$(readlink "$output/mkosi.extra/payload-root/usr/local/bin/example-link")" = example
test -f "$output/mkosi.extra/payload-root/usr/lib/systemd/system/example.service"
test -f "$output/mkosi.extra/payload-root/usr/lib/sysusers.d/example.conf"
test -f "$output/mkosi.extra/payload-root/usr/lib/tmpfiles.d/example.conf"
test -f "$output/mkosi.extra/payload-root/etc/skel/.config/example/config"

# Bazel copies what a source symlink points to, so a declared source file may not be, or lie below, a symlink in its
# package. The runfiles, execroot and workspace links in front of the fixture are Bazel's own and are followed.
package="${source_tree%%/testdata/*}"
for linked in linked-file linked-directory/marker; do
    if "$python" "$stage_script" --merge --output "$TEST_TMPDIR/linked-source" \
        --source-file "$source_tree/$linked" linked "$package" 2> "$TEST_TMPDIR/linked-source.err"; then
        echo "a symlinked source file was staged: $linked" >&2
        exit 1
    fi
    grep -q "is a symlink or lies below one" "$TEST_TMPDIR/linked-source.err"
    test ! -e "$TEST_TMPDIR/linked-source"
done
"$python" "$stage_script" --merge --output "$TEST_TMPDIR/regular-source" \
    --source-file "$source_tree/hello.txt" hello.txt "$package"
test "$(cat "$TEST_TMPDIR/regular-source/hello.txt")" = "declared source"
