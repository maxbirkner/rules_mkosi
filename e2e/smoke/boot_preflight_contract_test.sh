#!/bin/sh
set -eu

config="$1"

if ! /usr/bin/grep -Fq '"kernel_preflight":' "$config"; then
    echo "public boot configuration omitted the kernel preflight runfile" >&2
    exit 1
fi
