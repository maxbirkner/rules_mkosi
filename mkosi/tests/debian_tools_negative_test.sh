# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
PATH=
export PATH
candidate="$(rlocation "$1")"
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
