"""Validate a generated image artifact without precompiling shared sources."""

import os
import pathlib
import sys

from python.runfiles import runfiles

source_dir = runfiles.Create().Rlocation(
    os.path.join(os.environ["TEST_WORKSPACE"], "mkosi/tests")
)
sys.path.insert(0, source_dir)
import raw_image_validator


if __name__ == "__main__":
    raw_image_validator.main()
