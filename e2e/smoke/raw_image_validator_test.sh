# shellcheck shell=sh
# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
image="$(rlocation "$1")"
validator="$(rlocation "$2")"
python="$(rlocation "$3")"

# shellcheck disable=SC2123 # PATH is cleared on purpose so no host command can be resolved.
PATH=
export PATH
exec "$python" "$validator" "$image"
