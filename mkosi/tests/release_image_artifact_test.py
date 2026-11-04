"""Validate the release image artifact without sharing pyc outputs."""

import os
import sys

from python.runfiles import runfiles

sys.path.insert(0, runfiles.Create().Rlocation(os.path.join(os.environ["TEST_WORKSPACE"], "mkosi/tests")))
import raw_image_validator

if __name__ == "__main__":
    raw_image_validator.main()
