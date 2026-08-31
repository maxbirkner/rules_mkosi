"""Validate deterministic metadata on the materialized Debian repository."""

import pathlib
import stat
import sys
import unittest


class DebianSnapshotTreeMetadataTest(unittest.TestCase):
    def test_tree_metadata(self):
        root = pathlib.Path(sys.argv[1])
        self.assertTrue((root / "dists/trixie/InRelease").is_file())
        self.assertTrue((root / "pool").is_dir())
        paths = [root] + sorted(root.rglob("*"))
        for path in paths:
            mode = stat.S_IMODE(path.lstat().st_mode)
            if path.is_symlink():
                continue
            if path.is_dir():
                self.assertEqual(0o755, mode, path)
            else:
                self.assertEqual(0o644, mode, path)
            self.assertEqual(0, path.lstat().st_mtime_ns, path)


if __name__ == "__main__":
    unittest.main()
