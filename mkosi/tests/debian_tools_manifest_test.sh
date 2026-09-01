#!/bin/sh
set -eu

PATH=
export PATH
runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
runner=
mapping="$runfiles_root/_repo_mapping"
if [ -f "$mapping" ]; then
    while IFS= read -r mapping_line
    do
        case "$mapping_line" in
            ",mkosi_debian_tools,"*)
                repository="${mapping_line#*,mkosi_debian_tools,}"
                runner="$runfiles_root/$repository/launcher"
                break
                ;;
        esac
    done < "$mapping"
fi
[ -x "$runner" ] || {
    echo "static Debian launcher is missing" >&2
    exit 1
}
output="$("$runner" --help)"
case "$output" in
    *"Usage: debian-launcher"*"--validate-only"*) ;;
    *)
        echo "manifest launcher did not reach the Click CLI" >&2
        echo "$output" >&2
        exit 1
        ;;
esac
