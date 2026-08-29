#!/bin/sh
set -eu

code="$1"
vars="$2"
shell="$3"
expected_code="$4"
expected_vars="$5"
expected_shell="$6"
writable_vars="$7"

check_digest() {
    artifact="$1"
    expected="$2"
    label="$3"
    if [ ! -f "$artifact" ]; then
        echo "$label firmware artifact is missing: $artifact" >&2
        exit 1
    fi
    actual="$(/usr/bin/sha256sum "$artifact")"
    case "$actual" in
        "$expected "* ) ;;
        *)
            echo "$label firmware digest mismatch for $artifact (expected $expected): $actual" >&2
            exit 1
            ;;
    esac
}

check_digest "$code" "$expected_code" "OVMF_CODE"
check_digest "$vars" "$expected_vars" "OVMF_VARS"
check_digest "$shell" "$expected_shell" "UEFI shell"

if [ ! -f "$writable_vars" ] || [ ! -w "$writable_vars" ]; then
    echo "writable OVMF_VARS copy is not a regular writable file: $writable_vars" >&2
    exit 1
fi
