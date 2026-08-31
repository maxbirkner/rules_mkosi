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

python="$(resolve_runfile "$1")" || {
    echo "managed mkosi Python is missing from runfiles" >&2
    exit 1
}
main="$(resolve_runfile "$2")" || {
    echo "mkosi Python entrypoint is missing from runfiles" >&2
    exit 1
}

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

runtime_lib=
runtime_stdlib=
if [ -n "$manifest" ] && [ -f "$manifest" ]; then
    while read -r logical physical
    do
        case "$logical" in
            */lib/libpython3.11.so.1.0) runtime_lib=1 ;;
            */lib/python3.11/os.py) runtime_stdlib=1 ;;
        esac
    done < "$manifest"
else
    for runtime in "$runfiles_root"/*python* "$runfiles_root/_main"/*python*
    do
        if [ -f "$runtime/lib/libpython3.11.so.1.0" ]; then
            runtime_lib=1
        fi
        if [ -f "$runtime/lib/python3.11/os.py" ]; then
            runtime_stdlib=1
        fi
    done
fi
[ "$runtime_lib" = 1 ] || {
    echo "managed Python shared library is missing from runfiles" >&2
    exit 1
}
[ "$runtime_stdlib" = 1 ] || {
    echo "managed Python standard library is missing from runfiles" >&2
    exit 1
}

PATH=
export PATH
probe="$TEST_TMPDIR/pefile.version"
export MKOSI_PEFILE_PROBE="$probe"
customize_root=
for candidate in \
    "$runfiles_root/_main/mkosi/tests" \
    "$runfiles_root/mkosi/tests"
do
    if [ -f "$candidate/sitecustomize.py" ]; then
        customize_root="$candidate"
        break
    fi
done
PYTHONNOUSERSITE=1 \
PYTHONPATH="$customize_root:${main%/mkosi/__main__.py}:$pefile_root" \
    "$python" "$main" --version > "$TEST_TMPDIR/mkosi.version"
IFS= read -r version < "$TEST_TMPDIR/mkosi.version"
[ "$version" = "mkosi 27" ] || {
    echo "unexpected mkosi version: $version" >&2
    exit 1
}
[ -s "$probe" ]
