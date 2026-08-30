#!/bin/sh
set -eu
PATH=
export PATH

runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
module_file="$runfiles_root/_main/MODULE.bazel"
[ -f "$module_file" ] || module_file="$runfiles_root/rules_mkosi/MODULE.bazel"
[ -f "$module_file" ] || {
    echo "MODULE.bazel is missing from compatibility guard runfiles" >&2
    exit 1
}

floor=0
qemu=0
while IFS= read -r module_line
do
    case "$module_line" in
        *'">=7.7.0"'*) floor=1 ;;
        *'bazel_dep(name = "rules_qemu", version = "0.3.0")'*) qemu=1 ;;
    esac
done < "$module_file"
[ "$floor" -eq 1 ] || {
    echo "MODULE.bazel must advertise the supported Bazel 7.7.0 floor" >&2
    exit 1
}
[ "$qemu" -eq 1 ] || {
    echo "compatibility guard expects the pinned rules_qemu 0.3.0 dependency" >&2
    exit 1
}
