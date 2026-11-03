# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
image="$(rlocation "$1")"
validator="$(rlocation "$2")"
python="$(rlocation "$3")"

PATH=
export PATH
exec "$python" "$validator" "$image"
