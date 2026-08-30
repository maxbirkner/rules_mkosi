#!/bin/sh
set -eu

image="$TEST_SRCDIR/$TEST_WORKSPACE/$1"
[ -s "$image" ] || {
    echo "mkosi did not produce a non-empty raw disk image: $image" >&2
    exit 1
}
