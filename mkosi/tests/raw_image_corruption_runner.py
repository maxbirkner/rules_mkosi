"""Run the raw image corruption test with shared validator code as data."""

import sys
import unittest

import raw_image_corruption_test


if __name__ == "__main__":
    raw_image_corruption_test.IMAGE_PATH = sys.argv[1]
    unittest.main(
        argv=[sys.argv[0]],
        module=raw_image_corruption_test,
    )
