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
