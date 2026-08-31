#!/bin/sh
set -eu

runner="$1"
config="$2"
set +e
output="$("$runner" "$config" 2>&1)"
status="$?"
set -e

if [ "$status" -eq 0 ]; then
    echo "invalid QEMU boot entry unexpectedly succeeded" >&2
    exit 1
fi
case "$output" in
    *"QEMU_EXEC_FAILURE:"*) ;;
    *)
        echo "$output" >&2
        echo "boot lifecycle entry did not report QEMU_EXEC_FAILURE" >&2
        exit 1
        ;;
esac
