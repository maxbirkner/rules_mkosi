#!/bin/sh
set -eu
PATH=
export PATH

runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
helper="$(/usr/bin/find "$runfiles_root" -name qemu_ovmf_validate.sh -print -quit)"
code="$(/usr/bin/find "$runfiles_root" -path '*/x64/code.fd' -print -quit)"
vars="$(/usr/bin/find "$runfiles_root" -path '*/x64/vars.fd' -print -quit)"
shell="$(/usr/bin/find "$runfiles_root" -path '*/x64/shell.efi' -print -quit)"

if [ -z "$helper" ] || [ -z "$code" ] || [ -z "$vars" ] || [ -z "$shell" ]; then
    echo "could not locate QEMU/OVMF validation inputs in runfiles" >&2
    exit 1
fi

code_hash="$(/usr/bin/sha256sum "$code")"
code_hash="${code_hash%% *}"
vars_hash="$(/usr/bin/sha256sum "$vars")"
vars_hash="${vars_hash%% *}"
shell_hash="$(/usr/bin/sha256sum "$shell")"
shell_hash="${shell_hash%% *}"
vars_copy="$TEST_TMPDIR/OVMF_VARS.fd"
/bin/cp "$vars" "$vars_copy"

wrong_pair_log="$TEST_TMPDIR/wrong-pair.log"
if "$helper" "$code" "$vars" "$shell" "$vars_hash" "$code_hash" "$shell_hash" "$vars_copy" >"$wrong_pair_log" 2>&1; then
    echo "wrong OVMF_CODE/OVMF_VARS pairing unexpectedly passed validation" >&2
    exit 1
fi
/usr/bin/grep -Fq "digest mismatch" "$wrong_pair_log" || {
    echo "wrong OVMF pairing did not report an actionable digest mismatch" >&2
    /bin/cat "$wrong_pair_log" >&2
    exit 1
}

not_a_file="$TEST_TMPDIR/not-a-file"
/bin/mkdir "$not_a_file"
nonwritable_log="$TEST_TMPDIR/nonwritable.log"
if "$helper" "$code" "$vars" "$shell" "$code_hash" "$vars_hash" "$shell_hash" "$not_a_file" >"$nonwritable_log" 2>&1; then
    echo "non-file OVMF_VARS path unexpectedly passed validation" >&2
    exit 1
fi
/usr/bin/grep -Fq "not a regular writable file" "$nonwritable_log" || {
    echo "invalid OVMF_VARS path did not report an actionable writability error" >&2
    /bin/cat "$nonwritable_log" >&2
    exit 1
}
