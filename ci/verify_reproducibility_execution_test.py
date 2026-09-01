"""Tests for the reproducibility execution-log assertion."""

import importlib.util
import json
import os
import pathlib
import sys
import unittest


spec = importlib.util.spec_from_file_location("verify_execution", sys.argv[1])
verify_execution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_execution)


class VerifyExecutionTest(unittest.TestCase):
    def setUp(self):
        self.log = pathlib.Path(os.environ["TEST_TMPDIR"]) / "execution.json"

    def write(self, entries):
        self.log.write_text("\n".join(json.dumps(entry) for entry in entries))

    def test_accepts_independently_executed_named_actions(self):
        self.write(
            [
                {
                    "mnemonic": mnemonic,
                    "targetLabel": label,
                    "cacheHit": False,
                }
                for mnemonic, label in verify_execution.EXPECTED
            ]
        )
        verify_execution.verify(self.log, "first")

    def test_rejects_cached_action(self):
        self.write(
            [
                {
                    "mnemonic": mnemonic,
                    "targetLabel": label,
                    "cacheHit": mnemonic == "MkosiImage",
                }
                for mnemonic, label in verify_execution.EXPECTED
            ]
        )
        with self.assertRaisesRegex(SystemExit, "satisfied from a cache"):
            verify_execution.verify(self.log, "second")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
