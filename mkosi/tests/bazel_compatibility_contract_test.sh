#!/bin/sh
set -eu
PATH=
export PATH

module_file="$(/usr/bin/find "${RUNFILES_DIR:-$0.runfiles}" -path '*/MODULE.bazel' -print -quit)"
if [ -z "$module_file" ]; then
    echo "MODULE.bazel is missing from compatibility guard runfiles" >&2
    exit 1
fi

/usr/bin/grep -Fq 'bazel_compatibility = [">=7.7.0"]' "$module_file" || {
    echo "MODULE.bazel must advertise Bazel >=7.7.0 for rules_qemu 0.3.0" >&2
    exit 1
}
/usr/bin/grep -Fq 'bazel_dep(name = "rules_qemu", version = "0.3.0")' "$module_file" || {
    echo "compatibility guard expects the pinned rules_qemu 0.3.0 dependency" >&2
    exit 1
}
