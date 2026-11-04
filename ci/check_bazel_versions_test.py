"""Tests for the Bazel version consistency check."""

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from check_bazel_versions import check_copies, find_stray_copies, load_versions

CONSISTENT = {
    ".bazelversion": "1.2.3\n",
    "ci/bazel_versions.json": json.dumps(["1.2.3", "2.0.1"]),
    "e2e/smoke/.bazelversion": "1.2.3\n",
    "MODULE.bazel": 'module(bazel_compatibility = [">=1.2.3"])\n',
    "README.md": "| Bazel | 1 and 2. The minimum is 1.2.3. |\n",
    ".bcr/presubmit.yml": 'tasks:\n  a:\n    bazel: "1.2.3"\n  b:\n    bazel: "2.0.1"\n',
}


class CheckBazelVersionsTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        for path, text in CONSISTENT.items():
            self.write(path, text)

    def write(self, path: str, text: str) -> None:
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")

    def errors(self, *extra_paths: str) -> list[str]:
        versions = load_versions(self.root)
        paths = [*CONSISTENT, *extra_paths]
        return check_copies(self.root, versions) + find_stray_copies(self.root, paths, versions["tested"])

    def test_accepts_consistent_copies(self) -> None:
        self.assertEqual([], self.errors())

    def test_minimum_is_the_lowest_tested_version(self) -> None:
        self.write("ci/bazel_versions.json", json.dumps(["2.0.1", "1.2.3", "10.0.0"]))

        self.assertEqual(["1.2.3"], load_versions(self.root)["minimum"])

    def test_rejects_untested_default(self) -> None:
        self.write(".bazelversion", "1.9.0\n")

        with self.assertRaisesRegex(ValueError, "1.9.0 is missing"):
            load_versions(self.root)

    def test_rejects_malformed_version(self) -> None:
        self.write("ci/bazel_versions.json", json.dumps(["1.2.3", "9.x"]))

        with self.assertRaisesRegex(ValueError, "not a Bazel version: '9.x'"):
            load_versions(self.root)

    def test_reports_each_disagreeing_copy(self) -> None:
        self.write("e2e/smoke/.bazelversion", "2.0.1\n")
        self.write("MODULE.bazel", 'module(bazel_compatibility = [">=1.0.0"])\n')
        self.write(".bcr/presubmit.yml", 'tasks:\n  a:\n    bazel: "1.2.3"\n')

        errors = self.errors()

        self.assertEqual(3, len(errors))
        self.assertIn("e2e/smoke/.bazelversion: expected default", errors[0])
        self.assertIn("MODULE.bazel: expected minimum", errors[1])
        self.assertIn(".bcr/presubmit.yml: expected tested", errors[2])

    def test_reports_tested_version_in_other_file(self) -> None:
        self.write("docs/guide.md", "Run USE_BAZEL_VERSION=2.0.1 bazel test.\n")

        self.assertEqual(
            ["docs/guide.md: names a tested Bazel version; derive it from .bazelversion or ci/bazel_versions.json"],
            self.errors("docs/guide.md"),
        )

    def test_ignores_versions_inside_longer_numbers(self) -> None:
        self.write("ci.yml", "qemu 11.2.3 and 1.2.3.1, sentence end 1.2.30.\n")

        self.assertEqual([], self.errors("ci.yml"))

    def test_reports_version_at_sentence_end(self) -> None:
        self.write("notes.md", "The default is 1.2.3.\n")

        self.assertEqual(1, len(self.errors("notes.md")))


if __name__ == "__main__":
    unittest.main()
