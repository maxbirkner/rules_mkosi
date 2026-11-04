# shellcheck shell=sh
# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
# shellcheck disable=SC2123 # PATH is cleared on purpose so no host command can be resolved.
PATH=
export PATH

module_file="$(rlocation "$1")"
python_version="${2:?rules_mkosi Python version is required}"
qemu=0
python_lines=0
while IFS= read -r module_line
do
    case "$module_line" in
        *'bazel_dep(name = "rules_qemu", version = "0.3.0")'*) qemu=1 ;;
    esac
    case "$module_line" in
        *"python_version = \"$python_version\""*) python_lines=$((python_lines + 1)) ;;
        *"python_version = "*)
            echo "MODULE.bazel Python version differs from $python_version: $module_line" >&2
            exit 1
            ;;
    esac
done < "$module_file"
# The Python default, toolchain, and locked pip hub must all use the line that rules_mkosi's rules select.
[ "$python_lines" -eq 3 ] || {
    echo "MODULE.bazel must use Python $python_version for its default, toolchain, and pip hub" >&2
    exit 1
}
[ "$qemu" -eq 1 ] || {
    echo "compatibility guard expects the pinned rules_qemu 0.3.0 dependency" >&2
    exit 1
}
