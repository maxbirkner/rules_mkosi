"""Tests for execution-time image versions read from files."""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from mkosi.private import image_version

PRIVATE = pathlib.Path(image_version.__file__).parent
INVALID_CONTENTS = ("", "\n", "1\n\n", " 1", "1 ", "1\r\n", "1_2", "1-2", "1+2", "1~rc1", "1,2", "é")


class ImageVersionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.version = self.root / "version.txt"

    def tearDown(self):
        self.directory.cleanup()

    def test_reads_version_with_optional_trailing_newline(self):
        for content, expected in (
            ("7", "7"),
            ("1755129600.0123abc\n", "1755129600.0123abc"),
            ("1.2.RC1\n", "1.2.RC1"),
        ):
            with self.subTest(content=content):
                self.version.write_text(content)
                self.assertEqual(expected, image_version.read_image_version(self.version))

    def test_rejects_versions_that_image_version_rejects(self):
        for content in INVALID_CONTENTS:
            with self.subTest(content=content):
                self.version.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "invalid image_version_file .*image_version must be non-empty"):
                    image_version.read_image_version(self.version)

    def test_rejects_non_utf8_content(self):
        self.version.write_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "invalid image_version_file"):
            image_version.read_image_version(self.version)

    def run_tool(self, *arguments, environment=None):
        return subprocess.run(
            [sys.executable, *(os.fspath(argument) for argument in arguments)],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )

    def test_build_metadata_records_version_in_the_analysis_time_encoding(self):
        self.version.write_text("2\n")
        output = self.root / "metadata.json"
        metadata = {"mode": "release", "image": {"version": None, "id": "os"}, "artifacts": {"uki": True}}
        completed = self.run_tool(
            PRIVATE / "image_version.py",
            "build-metadata",
            "--metadata-json",
            json.dumps(metadata),
            "--image-version-file",
            self.version,
            "--output",
            output,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        # Starlark's json.encode sorts keys and uses no whitespace.
        self.assertEqual(
            '{"artifacts":{"uki":true},"image":{"id":"os","version":"2"},"mode":"release"}\n',
            output.read_text(),
        )

    def test_build_metadata_rejects_invalid_version(self):
        self.version.write_text("2-1\n")
        output = self.root / "metadata.json"
        completed = self.run_tool(
            PRIVATE / "image_version.py",
            "build-metadata",
            "--metadata-json",
            '{"image":{"id":"os","version":null}}',
            "--image-version-file",
            self.version,
            "--output",
            output,
        )
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("IMAGE_VERSION_INVALID: invalid image_version_file", completed.stderr)
        self.assertFalse(output.exists())


class RunMkosiTest(unittest.TestCase):
    """The image action rejects an invalid version before it checks the host or starts mkosi."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.version = self.root / "version.txt"

    def tearDown(self):
        self.directory.cleanup()

    def run_wrapper(self, *preamble, environment=None):
        # A missing kernel preflight and mkosi script would fail any later step.
        return subprocess.run(
            [
                sys.executable,
                os.fspath(PRIVATE / "run_mkosi.py"),
                os.fspath(self.root / "missing-mkosi.py"),
                "--kernel-preflight",
                os.fspath(self.root / "missing-preflight"),
                "--image-version-file",
                os.fspath(self.version),
                *preamble,
                "--",
                "--image-id=os",
                "build",
            ],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )

    def test_invalid_version_file_fails_the_action(self):
        environment = {key: value for key, value in os.environ.items() if key != "RULES_MKOSI_RELEASE_CHILD"}
        for preamble in ((), ("--debian-snapshot-repository", os.fspath(self.root))):
            for content in INVALID_CONTENTS:
                with self.subTest(preamble=preamble, content=content):
                    self.version.write_text(content, encoding="utf-8")
                    completed = self.run_wrapper(*preamble, environment=environment)
                    self.assertEqual(1, completed.returncode, completed.stderr)
                    self.assertIn("IMAGE_VERSION_INVALID: invalid image_version_file", completed.stderr)
                    self.assertIn("use only letters, digits and '.'", completed.stderr)
                    self.assertNotIn("preflight", completed.stderr)
                    self.assertNotIn("mkosi image assembly", completed.stderr)

    def test_valid_version_reaches_mkosi_after_image_id(self):
        spec = importlib.util.spec_from_file_location("run_mkosi", PRIVATE / "run_mkosi.py")
        run_mkosi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(run_mkosi)
        self.version.write_text("1755129600.0123abc\n")
        self.assertEqual(
            ["-C", "x", "--image-id=os", "--image-version=1755129600.0123abc", "build"],
            run_mkosi._with_image_version(
                ["-C", "x", "--image-id=os", "build"],
                run_mkosi._image_version_from_file(self.version),
            ),
        )
        with self.assertRaisesRegex(SystemExit, "requires exactly one --image-id="):
            run_mkosi._with_image_version(["build"], "1")


if __name__ == "__main__":
    unittest.main()
