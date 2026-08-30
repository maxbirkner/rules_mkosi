import hashlib
import pathlib
import re
import unittest


class DebianToolsLockDigestTest(unittest.TestCase):
    def test_checked_in_lock_digest(self):
        directory = pathlib.Path(__file__).resolve().parent
        lock = directory / "debian13.lock.json"
        provenance = (directory / "provenance.bzl").read_text(encoding="utf-8")
        expected = re.search(r'DEBIAN_TOOLS_LOCK_SHA256 = "([0-9a-f]{64})"', provenance).group(1)
        actual = hashlib.sha256(lock.read_bytes()).hexdigest()
        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
