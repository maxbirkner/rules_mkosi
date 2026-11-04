# shellcheck shell=sh
# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
test_script="$(rlocation "$1")"
python="$(rlocation "$2")"
validator="$(rlocation "$3")"

# shellcheck disable=SC2123 # PATH is cleared on purpose so no host command can be resolved.
PATH=
PYTHONPATH="${validator%/*}"
export PATH PYTHONPATH
exec "$python" "$test_script"
