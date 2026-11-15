"""Validate the reviewable shape of a materialized Debian repository against its lock."""

import json
import pathlib
import sys
import unittest


class DebianSnapshotArtifactTest(unittest.TestCase):
    def test_layout(self) -> None:
        repository = pathlib.Path(sys.argv[1]).resolve()
        lock = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
        architecture = lock["repository"]["architecture"]
        for relative in (
            "dists/trixie/InRelease",
            "dists/trixie/Release",
            "dists/trixie/Release.gpg",
            "dists/trixie/main/binary-%s/Packages" % architecture,
            "dists/trixie/main/binary-all/Packages",
        ):
            self.assertTrue((repository / relative).is_file(), relative)
        self.assertEqual(
            ["binary-all", "binary-" + architecture],
            sorted(path.name for path in (repository / "dists/trixie/main").iterdir()),
        )
        packages = sorted(str(path.relative_to(repository)) for path in (repository / "pool").rglob("*.deb"))
        self.assertEqual(sorted(package["filename"] for package in lock["packages"]), packages)
        self.assertTrue(all(path.endswith(("_%s.deb" % architecture, "_all.deb")) for path in packages))
        self.assertTrue(all((repository / package).stat().st_size > 0 for package in packages))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
