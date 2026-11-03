# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
PATH=
export PATH
runner="$(rlocation "$1")"
"$runner" --self-test-fd-swap
