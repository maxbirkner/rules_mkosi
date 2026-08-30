#!/bin/sh
set -eu

runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
manifest="${RUNFILES_MANIFEST_FILE:-}"

resolve_runfile() {
    requested="$1"
    if [ -n "$manifest" ] && [ -f "$manifest" ]; then
        while read -r logical physical
        do
            case "$logical" in
                "$requested"|../"$requested"|external/"$requested")
                    printf '%s\n' "$physical"
                    return 0
                    ;;
            esac
        done < "$manifest"
    fi
    for candidate in \
        "$runfiles_root/$requested" \
        "$runfiles_root/_main/$requested" \
        "$runfiles_root/${requested#external/}" \
        "$runfiles_root/_main/${requested#external/}"
    do
        if [ -f "$candidate" ] || [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

test_script="$(resolve_runfile "$1")" || {
    echo "consumer validator unit test is missing from runfiles" >&2
    exit 1
}
python="$(resolve_runfile "$2")" || {
    echo "managed Debian Python is missing from runfiles" >&2
    exit 1
}

PATH=
export PATH
exec "$python" "$test_script"
