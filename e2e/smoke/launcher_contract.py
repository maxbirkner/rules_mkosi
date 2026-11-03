import os
import pathlib
import sys
import sysconfig

assert os.environ["PYTHONNOUSERSITE"] == "1"
assert os.environ["PATH"] == ""
assert len(sys.argv) == 2
launcher = pathlib.Path(sys.argv[1])
assert launcher.is_symlink()
assert launcher.resolve().read_bytes()[:4] == b"\x7fELF"
# Bazel may store the managed runtime in a repository contents cache, so compare interpreters rather than paths.
assert pathlib.Path(sys.executable).resolve() == launcher.resolve()
# python-build-standalone runtimes are configured with this prefix; host interpreters are not.
assert "'--prefix=/install'" in sysconfig.get_config_var("CONFIG_ARGS")
