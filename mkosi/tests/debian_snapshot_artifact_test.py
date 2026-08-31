"""Validate the reviewable shape of a materialized Debian repository."""

import pathlib
import sys
import unittest


class DebianSnapshotArtifactTest(unittest.TestCase):
    def test_layout(self):
        root = pathlib.Path(sys.argv[1])
        repository = root
        for relative in (
            "dists/trixie/InRelease",
            "dists/trixie/Release",
            "dists/trixie/Release.gpg",
            "dists/trixie/main/binary-amd64/Packages",
            "dists/trixie/main/binary-all/Packages",
        ):
            self.assertTrue((repository / relative).is_file(), relative)
        packages = list((repository / "pool").rglob("*.deb"))
        self.assertEqual(135, len(packages))
        self.assertTrue(all(package.stat().st_size > 0 for package in packages))


if __name__ == "__main__":
    unittest.main()
