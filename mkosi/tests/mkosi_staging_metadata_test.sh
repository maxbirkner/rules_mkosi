#!/bin/sh
set -eu

python="$1"
stage_script="$2"
root="$TEST_TMPDIR/metadata"
rm -rf "$root"
mkdir -p "$root/config-a" "$root/config-b" "$root/source-a/dir" "$root/source-b/dir"
printf config > "$root/config-a/mkosi.conf"
cp "$root/config-a/mkosi.conf" "$root/config-b/mkosi.conf"
printf marker > "$root/source-a/dir/marker"
cp "$root/source-a/dir/marker" "$root/source-b/dir/marker"
chmod 600 "$root/source-a/dir/marker"
chmod 644 "$root/source-b/dir/marker"
touch -d '2001-01-01 00:00:00' "$root/config-a/mkosi.conf" "$root/source-a/dir/marker"
touch -d '2030-01-01 00:00:00' "$root/config-b/mkosi.conf" "$root/source-b/dir/marker"

"$python" "$stage_script" --output "$root/out-a" \
    --mapping "$root/config-a/mkosi.conf" mkosi.conf file \
    --mapping "$root/source-a" vendor/src tree
"$python" "$stage_script" --output "$root/out-b" \
    --mapping "$root/config-b/mkosi.conf" mkosi.conf file \
    --mapping "$root/source-b" vendor/src tree

test "$(stat -c '%a %Y' "$root/out-a/mkosi.conf")" = "644 0"
test "$(stat -c '%a %Y' "$root/out-a")" = "755 0"
test "$(stat -c '%a %Y' "$root/out-a/vendor")" = "755 0"
test "$(stat -c '%a %Y' "$root/out-a/vendor/src")" = "755 0"
test "$(stat -c '%a %Y' "$root/out-a/vendor/src/dir")" = "755 0"
test "$(stat -c '%a %Y' "$root/out-a/vendor/src/dir/marker")" = "644 0"
test "$(stat -c '%a %Y' "$root/out-b/mkosi.conf")" = "644 0"
test "$(stat -c '%a %Y' "$root/out-b")" = "755 0"
test "$(stat -c '%a %Y' "$root/out-b/vendor")" = "755 0"
test "$(stat -c '%a %Y' "$root/out-b/vendor/src")" = "755 0"
test "$(stat -c '%a %Y' "$root/out-b/vendor/src/dir")" = "755 0"
test "$(stat -c '%a %Y' "$root/out-b/vendor/src/dir/marker")" = "644 0"
cmp "$root/out-a/mkosi.conf" "$root/out-b/mkosi.conf"
cmp "$root/out-a/vendor/src/dir/marker" "$root/out-b/vendor/src/dir/marker"
