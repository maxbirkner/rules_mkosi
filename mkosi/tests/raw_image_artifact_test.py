"""Validate a generated image artifact without precompiling shared sources."""

import os
import sys

from python.runfiles import runfiles

source_dir = runfiles.Create().Rlocation(
    os.path.join(os.environ["TEST_WORKSPACE"], "mkosi/tests")
)
sys.path.insert(0, source_dir)
import raw_image_validator


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: raw_image_artifact_test.py IMAGE")
    raw_image_validator.validate(raw_image_validator.image_path(sys.argv[1]))
