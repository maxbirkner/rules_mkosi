import os
import pathlib
import sys

assert os.environ["PYTHONNOUSERSITE"] == "1"
assert os.environ["PATH"] == ""
assert "rules_python" in str(pathlib.Path(sys.executable).resolve())
assert len(sys.argv) == 2
launcher = pathlib.Path(sys.argv[1])
assert launcher.is_symlink()
assert launcher.resolve().read_bytes()[:4] == b"\x7fELF"
