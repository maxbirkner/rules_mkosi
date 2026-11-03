# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
python="$(rlocation "$1")"
main="$(rlocation "$2")"
customize="$(rlocation "$3")"
runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
manifest="${RUNFILES_MANIFEST_FILE:-}"

pefile_root=
if [ -n "$manifest" ] && [ -f "$manifest" ]; then
    while read -r logical physical
    do
        case "$logical" in
            */pefile.py)
                pefile_root="${physical%/pefile.py}"
                break
                ;;
        esac
    done < "$manifest"
fi
if [ -z "$pefile_root" ]; then
    for candidate in \
        "$runfiles_root"/*pefile*/site-packages/pefile.py \
        "$runfiles_root/_main"/*pefile*/site-packages/pefile.py
    do
        if [ -f "$candidate" ]; then
            pefile_root="${candidate%/pefile.py}"
            break
        fi
    done
fi
[ -n "$pefile_root" ] || {
    echo "pinned pefile module is missing from runfiles" >&2
    exit 1
}

runtime_stdlib=
if [ -n "$manifest" ] && [ -f "$manifest" ]; then
    while read -r logical physical
    do
        case "$logical" in
            */lib/python3.14/os.py) runtime_stdlib=1 ;;
        esac
    done < "$manifest"
else
    for runtime in "$runfiles_root"/*python* "$runfiles_root/_main"/*python*
    do
        if [ -f "$runtime/lib/python3.14/os.py" ]; then
            runtime_stdlib=1
        fi
    done
fi
[ "$runtime_stdlib" = 1 ] || {
    echo "managed Python standard library is missing from runfiles" >&2
    exit 1
}

PATH=
export PATH
probe="$TEST_TMPDIR/pefile.version"
export MKOSI_PEFILE_PROBE="$probe"
PYTHONNOUSERSITE=1 \
PYTHONPATH="${customize%/*}:${main%/mkosi/__main__.py}:$pefile_root" \
    "$python" "$main" --version > "$TEST_TMPDIR/mkosi.version"
IFS= read -r version < "$TEST_TMPDIR/mkosi.version"
[ "$version" = "mkosi 27" ] || {
    echo "unexpected mkosi version: $version" >&2
    exit 1
}
[ -s "$probe" ]
