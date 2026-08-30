#!/bin/sh
set -eu

fixture="${1:?fixture name is required}"
root="$(CDPATH= cd -- "$(dirname "$0")/$fixture" && pwd)"
bazel_command="${BAZEL:-bazel}"
lockfile_mode="${LOCKFILE_MODE:-off}"

cd "$root"

case "$fixture" in
    default|explicit)
        version="$("$bazel_command" --nosystem_rc --nohome_rc \
            run --lockfile_mode="$lockfile_mode" @mkosi_toolchains//:mkosi -- --version)"
        [ "$version" = "mkosi 27" ]
        ;;
    unsupported)
        expected="Unsupported mkosi version 26. Supported versions: 27."
        ;;
    conflicting_root)
        expected="Only one mkosi toolchain may be configured."
        ;;
    nonroot_name)
        expected="Only the root module may override the mkosi toolchain name."
        ;;
    root_dependency)
        expected="Conflicting mkosi versions: root requests 27, dependency requests 26."
        ;;
    *)
        echo "unknown fixture: $fixture" >&2
        exit 2
        ;;
esac

if [ "${expected:-}" ]; then
    set +e
    output="$("$bazel_command" --nosystem_rc --nohome_rc mod deps \
        --lockfile_mode="$lockfile_mode" 2>&1)"
    status=$?
    set -e
    [ "$status" -ne 0 ]
    case "$output" in
        *"$expected"*) ;;
        *)
            echo "$output" >&2
            echo "missing expected diagnostic: $expected" >&2
            exit 1
            ;;
    esac
fi
