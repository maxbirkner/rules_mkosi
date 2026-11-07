#!/bin/sh
set -eu

fixture="${1:?fixture name is required}"
root="$(CDPATH='' cd -- "$(dirname "$0")/$fixture" && pwd)"
bazel_command="${BAZEL:-bazel}"
lockfile_mode="${LOCKFILE_MODE:-off}"

cd "$root"

if ! grep -Fqx 'import %workspace%/../../../.bazelrc.ci' .bazelrc; then
    echo "$fixture/.bazelrc must import .bazelrc.ci, which retries repository downloads" >&2
    exit 1
fi

link_graph() {
    "$bazel_command" --nosystem_rc --nohome_rc aquery --lockfile_mode="$lockfile_mode" \
        --output=text "$@"
}

# Fails unless the link commands name the target triple $3 and never $4.
require_link_toolchain() {
    case "$2" in
        *"$3"*) ;;
        *)
            echo "$1 did not link with the $3 toolchain" >&2
            echo "$2" >&2
            exit 1
            ;;
    esac
    case "$2" in
        *"$4"*)
            echo "$1 linked with the $4 toolchain" >&2
            echo "$2" >&2
            exit 1
            ;;
    esac
}

case "$fixture" in
    consumer_isolation)
        "$bazel_command" --nosystem_rc --nohome_rc test --lockfile_mode="$lockfile_mode" //...
        # The toolchain consumes the launcher in the execution configuration; tests consume it as target data.
        bootstrap_closure='deps(@mkosi_debian_tools//:launcher) + deps(@mkosi_debian_tools//:toolchain)'
        bootstrap_links="mnemonic(\"CppLink\", filter(\":(launcher|namespace_runner)_binary\$\", $bootstrap_closure))"
        graph="$(link_graph "$bootstrap_links")"
        for action in "launcher_binary'" "namespace_runner_binary'" "launcher_binary [for tool]'"; do
            case "$graph" in
                *"Linking external/"*"/$action"*) ;;
                *)
                    echo "bootstrap link graph lacks $action" >&2
                    exit 1
                    ;;
            esac
        done
        require_link_toolchain "selected bootstrap platform" "$graph" \
            x86_64-linux-musl x86_64-linux-gnu
        # rules_mkosi's static toolchain also outranks the consumer's first-registered glibc toolchain with the
        # default bootstrap platform.
        graph="$(link_graph \
            --@rules_mkosi//mkosi/toolchain:bootstrap_platform=@rules_mkosi//mkosi/toolchain:inherit_platform \
            "$bootstrap_links")"
        require_link_toolchain "default bootstrap platform" "$graph" \
            x86_64-linux-musl x86_64-linux-gnu
        graph="$(link_graph 'mnemonic("CppLink", deps(@rules_mkosi//mkosi:kernel_preflight))')"
        require_link_toolchain "consumer target platform" "$graph" \
            x86_64-linux-gnu x86_64-linux-musl
        ;;
    llvm_consumer)
        LOCKFILE_MODE="$lockfile_mode" "$root/../../../ci/check-lazy-toolchain-fetch.sh" \
            --uses-llvm \
            --consumer-cc-target //:consumer_cc \
            --bootstrap-target @mkosi_debian_tools//:namespace_runner \
            "$root" //:plain_test
        # The consumer's registration of the same cc_toolchain links its own target dynamically against glibc,
        # while rules_mkosi's bootstrap executable links statically against musl.
        graph="$(link_graph 'mnemonic("CppLink", deps(//:consumer_cc))')"
        require_link_toolchain "consumer target" "$graph" x86_64-linux-gnu x86_64-linux-musl
        graph="$(link_graph \
            'mnemonic("CppLink", filter(":namespace_runner_binary$", deps(@mkosi_debian_tools//:namespace_runner)))')"
        require_link_toolchain "bootstrap executable" "$graph" x86_64-linux-musl x86_64-linux-gnu
        "$bazel_command" --nosystem_rc --nohome_rc build --lockfile_mode="$lockfile_mode" \
            //:consumer_cc @mkosi_debian_tools//:namespace_runner
        execution_root="$("$bazel_command" --nosystem_rc --nohome_rc info --lockfile_mode="$lockfile_mode" \
            execution_root)"
        consumer="$("$bazel_command" --nosystem_rc --nohome_rc cquery --lockfile_mode="$lockfile_mode" \
            --output=files //:consumer_cc)"
        runner="$("$bazel_command" --nosystem_rc --nohome_rc cquery --lockfile_mode="$lockfile_mode" \
            --output=files @mkosi_debian_tools//:namespace_runner)"
        consumer_headers="$(readelf --program-headers --wide "$execution_root/$consumer")"
        runner_headers="$(readelf --program-headers --wide "$execution_root/$runner")"
        case "$consumer_headers" in
            *INTERP*) ;;
            *)
                echo "consumer_cc is not dynamically linked" >&2
                exit 1
                ;;
        esac
        case "$runner_headers" in
            *INTERP* | *DYNAMIC*)
                echo "the namespace runner is not fully static" >&2
                exit 1
                ;;
        esac
        ;;
    rules_cc_first)
        LOCKFILE_MODE="$lockfile_mode" "$root/../../../ci/check-lazy-toolchain-fetch.sh" \
            --consumer-cc-target //:consumer_cc \
            --bootstrap-target @mkosi_debian_tools//:namespace_runner \
            "$root" //:plain_test
        ;;
    default|explicit)
        definition="$("$bazel_command" --nosystem_rc --nohome_rc \
            query --lockfile_mode="$lockfile_mode" @mkosi_toolchains//:mkosi_toolchain --output=build)"
        case "$definition" in
            *'version = "27.1"'*) ;;
            *)
                echo "mkosi toolchain did not resolve to version 27.1" >&2
                echo "$definition" >&2
                exit 1
                ;;
        esac
        ;;
    unsupported)
        expected="Unsupported mkosi version 27. Supported versions: 27.1."
        ;;
    conflicting_root)
        expected="Only one mkosi toolchain may be configured."
        ;;
    nonroot_name)
        expected="Only the root module may override the mkosi toolchain name."
        ;;
    root_dependency)
        expected="Conflicting mkosi versions: root requests 27.1, dependency requests 26."
        ;;
    snapshot_name_conflict)
        expected="debian_tools.snapshot repository consumer_debian requested by mkosi_extension_snapshot_name_conflict is already declared by mkosi_extension_snapshot_name_conflict"
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
