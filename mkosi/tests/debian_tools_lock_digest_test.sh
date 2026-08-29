#!/bin/sh
set -eu
PATH=
export PATH
runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
lock="$runfiles_root/_main/mkosi/debian/debian13.lock.json"
provenance="$runfiles_root/_main/mkosi/debian/provenance.bzl"
[ -f "$lock" ] || lock="$runfiles_root/rules_mkosi/mkosi/debian/debian13.lock.json"
[ -f "$provenance" ] || provenance="$runfiles_root/rules_mkosi/mkosi/debian/provenance.bzl"
expected=
while IFS= read -r line
do
    case "$line" in
        DEBIAN_TOOLS_LOCK_SHA256*) expected="${line#*\"}"; expected="${expected%%\"*}" ;;
    esac
done < "$provenance"
actual="$(/usr/bin/sha256sum "$lock")"
actual="${actual%% *}"
[ -n "$expected" ] && [ "$actual" = "$expected" ] || {
    echo "Debian lock digest mismatch: expected=$expected actual=$actual" >&2
    exit 1
}
