#!/bin/sh
set -eu

output="$("$1" --help)"
case "$output" in
    *"Usage:"*) ;;
    *)
        echo "$output" >&2
        echo "Debian launcher help is missing its usage line" >&2
        exit 1
        ;;
esac
