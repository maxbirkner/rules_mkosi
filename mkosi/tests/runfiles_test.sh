# shellcheck shell=sh
# Sourced by run_with_runfiles.sh; $1 and $2 are the rlocation paths Bazel passes for runfiles_test.sh and
# @bazel_skylib//:LICENSE. They must equal the keys Bazel writes to runfiles manifests and trees.
# shellcheck disable=SC2123 # PATH is cleared on purpose so no host command can be resolved.
PATH=
export PATH
main_key=_main/mkosi/tests/runfiles_test.sh
external_key=bazel_skylib+/LICENSE

# Fails unless rlocation, run with RUNFILES_DIR=$1 and RUNFILES_MANIFEST_FILE=$2, resolves $3 to $4.
assert_resolves_to() {
    resolved="$(RUNFILES_DIR="$1" RUNFILES_MANIFEST_FILE="$2" rlocation "$3")"
    [ "$resolved" = "$4" ] || {
        echo "$3 resolved to $resolved instead of $4" >&2
        exit 1
    }
}

missing_tree="$TEST_TMPDIR/missing-tree"
manifest="$TEST_TMPDIR/MANIFEST"
printf '%s %s\n' "$main_key" /manifest/main "$external_key" /manifest/external > "$manifest"
assert_resolves_to "$missing_tree" "$manifest" "$1" /manifest/main
assert_resolves_to "$missing_tree" "$manifest" "$2" /manifest/external

tree="$TEST_TMPDIR/tree"
/bin/mkdir -p "$tree/${main_key%/*}" "$tree/${external_key%/*}"
: > "$tree/$main_key"
: > "$tree/$external_key"
assert_resolves_to "$tree" "" "$1" "$tree/$main_key"
assert_resolves_to "$tree" "" "$2" "$tree/$external_key"

if (RUNFILES_DIR="$tree" RUNFILES_MANIFEST_FILE="$manifest" rlocation _main/absent 2>/dev/null); then
    echo "a missing runfile was resolved" >&2
    exit 1
fi
