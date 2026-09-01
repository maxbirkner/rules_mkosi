"""Prove Bazel executes release checks without a routable network namespace."""

import os
import socket
import sys
import unittest

from python.runfiles import runfiles

source_dir = runfiles.Create().Rlocation(
    os.path.join(os.environ["TEST_WORKSPACE"], "mkosi/tests")
)
sys.path.insert(0, source_dir)
import raw_image_validator


class ReleaseNetworkIsolationTest(unittest.TestCase):
    def test_undeclared_network_access_is_unavailable(self):
        raw_image_validator.validate(raw_image_validator.image_path(sys.argv[1]))
        self.assertEqual(["lo"], sorted(name for _, name in socket.if_nameindex()))
        with self.assertRaises(OSError):
            socket.create_connection(("1.1.1.1", 443), timeout=1)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
