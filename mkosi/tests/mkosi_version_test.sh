#!/bin/sh
set -eu

runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
executable=
if [ -f "${RUNFILES_MANIFEST_FILE:-}" ]; then
    while read -r logical physical
    do
        case "$logical" in
            *mkosi_toolchains/mkosi_cli)
                executable="$physical"
                break
                ;;
        esac
    done < "$RUNFILES_MANIFEST_FILE"
fi

for repository in "$runfiles_root"/*mkosi*toolchains
do
    if [ -z "$executable" ] && [ -x "$repository/mkosi_cli" ]; then
        executable="$repository/mkosi_cli"
        break
    fi
done

for candidate in \
    "$runfiles_root/+mkosi+mkosi_toolchains/mkosi_cli" \
    "$runfiles_root/+rules_mkosi+mkosi_toolchains/mkosi_cli" \
    "$runfiles_root/rules_mkosi++mkosi+mkosi_toolchains/mkosi_cli" \
    "$runfiles_root/mkosi_toolchains/mkosi_cli"
do
    if [ -z "$executable" ] && [ -x "$candidate" ]; then
        executable="$candidate"
        break
    fi
done

if [ -z "$executable" ]; then
    echo "mkosi toolchain executable is missing from runfiles" >&2
    exit 1
fi

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
export PYTHONPATH="$customize_root"
version="$("$executable" --version)"
[ "$version" = "mkosi 27" ] || {
    echo "unexpected mkosi version: $version" >&2
    exit 1
}
[ -s "$probe" ]
