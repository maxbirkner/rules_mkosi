#!/bin/sh
set -eu
PATH=
export PATH
runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
candidate="$runfiles_root/_main/mkosi/tests/debian_tools_missing_component.sh"
if [ ! -x "$candidate" ]; then
    candidate="$runfiles_root/rules_mkosi/mkosi/tests/debian_tools_missing_component.sh"
fi
log="$TEST_TMPDIR/missing-component.log"
if "$candidate" >"$log" 2>&1; then
    echo "missing Debian tools component unexpectedly passed" >&2
    exit 1
fi
expected="Debian tools component is missing from the pinned tree: apt-get"
while IFS= read -r line
do
    [ "$line" = "$expected" ] && exit 0
done < "$log"
echo "missing-component diagnostic was not precise" >&2
while IFS= read -r line
do
    echo "$line" >&2
done < "$log"
exit 1
