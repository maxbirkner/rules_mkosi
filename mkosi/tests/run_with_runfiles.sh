#!/bin/sh
# Sources the test script named by the rlocation path in $1 with the remaining arguments and an rlocation function.
# Only shell builtins are used, so sourced scripts may clear PATH before resolving runfiles.
set -eu

# Prints the manifest entry for rlocation path $1, or fails if the manifest does not list it.
rlocation_from_manifest() {
    [ -f "${RUNFILES_MANIFEST_FILE:-}" ] || return 1
    while read -r logical physical
    do
        if [ "$logical" = "$1" ]; then
            printf '%s\n' "$physical"
            return 0
        fi
    done < "$RUNFILES_MANIFEST_FILE"
    return 1
}

# Prints the runfiles tree path of rlocation path $1, or fails if it does not exist.
rlocation_from_directory() {
    candidate="${RUNFILES_DIR:-$0.runfiles}/$1"
    [ -e "$candidate" ] || return 1
    printf '%s\n' "$candidate"
}

# Prints the absolute path of rlocation path $1 in manifest or directory mode, or fails with a diagnostic.
rlocation() {
    rlocation_from_manifest "$1" || rlocation_from_directory "$1" || {
        echo "runfile is missing: $1" >&2
        return 1
    }
}

test_script="$(rlocation "${1:?rlocation path of the test script is required}")"
shift
# shellcheck source=/dev/null
. "$test_script"
