# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
PATH=
export PATH
runner="$(rlocation "$1")"
output="$("$runner" --help)"
case "$output" in
    *"Usage: debian-launcher"*"--validate-only"*) ;;
    *)
        echo "manifest launcher did not reach the Click CLI" >&2
        echo "$output" >&2
        exit 1
        ;;
esac
