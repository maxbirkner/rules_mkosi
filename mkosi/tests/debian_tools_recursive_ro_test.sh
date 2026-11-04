# shellcheck shell=sh
# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
# shellcheck disable=SC2123 # PATH is cleared on purpose so no host command can be resolved.
PATH=
export PATH
runner="$(rlocation "$1")"
"$runner" --self-test-recursive-ro
