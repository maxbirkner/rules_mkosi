"""Prove Bazel executes release checks without a routable network namespace."""

import socket
import sys
import unittest


class ReleaseNetworkIsolationTest(unittest.TestCase):
    def test_undeclared_network_access_is_unavailable(self):
        self.assertEqual(["lo"], sorted(name for _, name in socket.if_nameindex()))
        with self.assertRaises(OSError):
            socket.create_connection(("1.1.1.1", 443), timeout=1)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
