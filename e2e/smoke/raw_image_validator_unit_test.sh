# Sourced by run_with_runfiles.sh; arguments are rlocation paths.
test_script="$(rlocation "$1")"
python="$(rlocation "$2")"
validator="$(rlocation "$3")"

PATH=
PYTHONPATH="${validator%/*}"
export PATH PYTHONPATH
exec "$python" "$test_script"
