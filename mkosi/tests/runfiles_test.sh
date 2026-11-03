# Sourced by run_with_runfiles.sh; arguments are rlocation paths of a main-repository and an external-repository file.
PATH=
export PATH
manifest="${RUNFILES_MANIFEST_FILE:-${RUNFILES_DIR:-$0.runfiles}/MANIFEST}"
[ -f "$manifest" ] || {
    echo "Bazel did not provide a runfiles manifest: $manifest" >&2
    exit 1
}

# Fails unless rlocation resolves $1 to an existing file through the manifest alone.
assert_manifest_lookup() {
    resolved="$(RUNFILES_DIR="$TEST_TMPDIR/no-runfiles-tree" RUNFILES_MANIFEST_FILE="$manifest" rlocation "$1")" || {
        echo "manifest lookup failed for $1" >&2
        exit 1
    }
    [ -f "$resolved" ] || {
        echo "manifest lookup of $1 returned a missing file: $resolved" >&2
        exit 1
    }
}

assert_manifest_lookup "$1"
assert_manifest_lookup "$2"

tree="$TEST_TMPDIR/runfiles-tree"
/bin/mkdir -p "$tree/_main"
: > "$tree/_main/present"
resolved="$(RUNFILES_DIR="$tree" RUNFILES_MANIFEST_FILE= rlocation _main/present)"
[ "$resolved" = "$tree/_main/present" ] || {
    echo "directory lookup returned $resolved" >&2
    exit 1
}

if (RUNFILES_DIR="$tree" RUNFILES_MANIFEST_FILE="$manifest" rlocation _main/absent 2>/dev/null); then
    echo "a missing runfile was resolved" >&2
    exit 1
fi
