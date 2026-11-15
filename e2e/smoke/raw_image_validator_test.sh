# shellcheck shell=sh
# Sourced by run_with_runfiles.sh; the first three arguments are rlocation paths, an optional fourth is the expected
# ext4 hash seed of the root file system.
image="$(rlocation "$1")"
validator="$(rlocation "$2")"
python="$(rlocation "$3")"

# shellcheck disable=SC2123 # PATH is cleared on purpose so no host command can be resolved.
PATH=
export PATH
shift 3
exec "$python" "$validator" "$image" "$@"
