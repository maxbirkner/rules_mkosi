import os
import pathlib
import sys

assert os.environ["PYTHONNOUSERSITE"] == "1"
assert "rules_python" in str(pathlib.Path(sys.executable).resolve())
assert len(sys.argv) == 2
assert pathlib.Path(sys.argv[1]).name == "launcher_contract.py"
