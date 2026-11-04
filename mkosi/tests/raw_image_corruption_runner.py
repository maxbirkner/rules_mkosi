"""Run the raw image corruption test with shared validator code as data."""

import os
import sys
import unittest

from python.runfiles import runfiles

sys.path.insert(0, runfiles.Create().Rlocation(os.path.join(os.environ["TEST_WORKSPACE"], "mkosi/tests")))
import raw_image_corruption_test

if __name__ == "__main__":
    raw_image_corruption_test.IMAGE_PATH = sys.argv[1]
    unittest.main(
        argv=[sys.argv[0]],
        module=raw_image_corruption_test,
    )
