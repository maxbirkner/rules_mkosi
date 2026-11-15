"""Resolves the $(rootpath) arguments of a test to their runfiles locations."""

import os
import pathlib

from python.runfiles import runfiles


def resolve_runfile(path: str) -> pathlib.Path:
    """Returns the runfiles location of a $(rootpath) of the main repository or of an external repository."""
    if path.startswith("../"):
        path = path[3:]
    elif not path.startswith("external/"):
        path = os.path.join(os.environ["TEST_WORKSPACE"], path)
    return pathlib.Path(runfiles.Create().Rlocation(path))
