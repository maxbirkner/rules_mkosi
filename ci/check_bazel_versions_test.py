"""Tests for the Bazel version consistency check."""

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from check_bazel_versions import check_copies, check_presubmit, load_versions


def presubmit(*tasks: tuple[str, str]) -> str:
    """Returns a BCR presubmit with one task per Bazel version and lockfile mode."""
    lines = ["bcr_test_module:", "  matrix:", "    platform:", '      - "debian11"', "  tasks:"]
    for index, (version, lockfile_mode) in enumerate(tasks):
        lines += [
            f"    task{index}:",
            f'      bazel: "{version}"',
            "      test_flags:",
            f'        - "--lockfile_mode={lockfile_mode}"',
        ]
    return "\n".join(lines) + "\n"


CONSISTENT = {
    ".bazelversion": "1.2.3\n",
    "ci/bazel_versions.json": json.dumps(["1.2.3", "2.0.1"]),
    "e2e/smoke/.bazelversion": "1.2.3\n",
    "MODULE.bazel": 'module(bazel_compatibility = [">=1.2.3"])\n',
    "README.md": "| Bazel | 1 and 2. The minimum is 1.2.3. |\n",
    ".bcr/presubmit.yml": presubmit(("1.2.3", "error"), ("2.0.1", "off")),
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

    def errors(self) -> list[str]:
        versions = load_versions(self.root)
        return check_copies(self.root, versions) + check_presubmit(self.root, versions)

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
        self.write(".bcr/presubmit.yml", presubmit(("1.2.3", "error")))

        errors = self.errors()

        self.assertEqual(3, len(errors))
        self.assertIn("e2e/smoke/.bazelversion: expected default", errors[0])
        self.assertIn("MODULE.bazel: expected minimum", errors[1])
        self.assertIn(".bcr/presubmit.yml: expected tested", errors[2])

    def test_requires_strict_lockfile_task_on_default_version(self) -> None:
        self.write(".bazelversion", "2.0.1\n")
        self.write("e2e/smoke/.bazelversion", "2.0.1\n")

        self.assertEqual(
            [".bcr/presubmit.yml: expected strict-lockfile Bazel versions ['2.0.1'], found ['1.2.3']"],
            self.errors(),
        )

    def test_rejects_strict_lockfile_on_other_versions(self) -> None:
        self.write(".bcr/presubmit.yml", presubmit(("1.2.3", "error"), ("2.0.1", "error")))

        self.assertEqual(
            [".bcr/presubmit.yml: expected strict-lockfile Bazel versions ['1.2.3'], found ['1.2.3', '2.0.1']"],
            self.errors(),
        )

    def test_ignores_versions_outside_presubmit_tasks(self) -> None:
        text = presubmit(("1.2.3", "error"), ("2.0.1", "off")).replace("  matrix:", '  bazel: "9.9.9"\n  matrix:')
        self.write(".bcr/presubmit.yml", text)

        self.assertEqual([], self.errors())


if __name__ == "__main__":
    unittest.main()
