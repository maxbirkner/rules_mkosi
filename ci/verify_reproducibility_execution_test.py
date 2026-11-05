"""Tests for the reproducibility execution-log assertion."""

import importlib.util
import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("verify_execution", sys.argv[1])
assert spec is not None and spec.loader is not None
verify_execution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_execution)


class VerifyExecutionTest(unittest.TestCase):
    def setUp(self):
        self.log = pathlib.Path(os.environ["TEST_TMPDIR"]) / "execution.json"

    def write(self, entries):
        self.log.write_text("\n".join(json.dumps(entry) for entry in entries))

    def write_subject(self, subject, cached_mnemonic=None, extra=()):
        self.write(
            [
                {
                    "mnemonic": mnemonic,
                    "targetLabel": label,
                    "cacheHit": mnemonic == cached_mnemonic,
                }
                for mnemonic, label in verify_execution.SUBJECTS[subject]
            ]
            + list(extra)
        )

    def test_accepts_independently_executed_named_actions(self):
        self.write_subject("release")
        verify_execution.verify(self.log, "first")

    def test_rejects_cached_action(self):
        self.write_subject("release", cached_mnemonic="MkosiImage")
        with self.assertRaisesRegex(SystemExit, "satisfied from a cache"):
            verify_execution.verify(self.log, "second")

    def test_accepts_independently_executed_bootstrap_actions(self):
        self.write_subject("bootstrap")
        verify_execution.verify(self.log, "first", "bootstrap")

    def test_rejects_cached_bootstrap_link(self):
        self.write_subject("bootstrap", cached_mnemonic="CppLink")
        with self.assertRaisesRegex(SystemExit, "CppLink .*:launcher_binary: action was satisfied from a cache"):
            verify_execution.verify(self.log, "second", "bootstrap")

    def test_rejects_missing_bootstrap_archive(self):
        self.write(
            [
                {"mnemonic": mnemonic, "targetLabel": label, "cacheHit": False}
                for mnemonic, label in verify_execution.SUBJECTS["bootstrap"]
                if mnemonic != "BuildDebianToolsArchive"
            ]
        )
        with self.assertRaisesRegex(SystemExit, "BuildDebianToolsArchive .*: expected one execution, found 0"):
            verify_execution.verify(self.log, "first", "bootstrap")

    def test_rejects_executed_disabled_action_placeholder(self):
        strip = {"mnemonic": "CcStrip", "targetLabel": "//x:y", "cacheHit": False, "commandArgs": ["/usr/bin/false"]}
        self.write_subject("bootstrap", extra=[strip])
        with self.assertRaisesRegex(SystemExit, "CcStrip //x:y: executed the disabled-action placeholder"):
            verify_execution.verify(self.log, "first", "bootstrap")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
