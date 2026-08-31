"""Hermetic entrypoint for managed Python test scripts."""

import os
import runpy
import sys

os.environ["PATH"] = ""
if len(sys.argv) < 2:
    raise SystemExit("managed Python bootstrap requires a source script")

source = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(source, run_name="__main__")
