"""Tests for the two-stage base reuse execution-log assertion."""

import importlib.util
import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(sys.argv[1]).parent))
spec = importlib.util.spec_from_file_location("verify_two_stage_cache", sys.argv[1])
verify_cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_cache)


def _entry(key, cache_hit=False):
    mnemonic, label = key
    return {"mnemonic": mnemonic, "targetLabel": label, "cacheHit": cache_hit, "metrics": {"totalTime": "1s"}}


class VerifyTwoStageCacheTest(unittest.TestCase):
    def setUp(self):
        directory = pathlib.Path(os.environ["TEST_TMPDIR"])
        self.first = directory / "first.json"
        self.second = directory / "second.json"

    def write(self, first, second):
        self.first.write_text("\n".join(json.dumps(entry) for entry in first))
        self.second.write_text("\n".join(json.dumps(entry) for entry in second))

    def test_accepts_reused_base(self):
        self.write([_entry(verify_cache.BASE), _entry(verify_cache.IMAGE)], [_entry(verify_cache.IMAGE)])
        verify_cache.verify(self.first, self.second)

    def test_accepts_base_satisfied_from_a_cache(self):
        self.write(
            [_entry(verify_cache.BASE), _entry(verify_cache.IMAGE)],
            [_entry(verify_cache.BASE, cache_hit=True), _entry(verify_cache.IMAGE)],
        )
        verify_cache.verify(self.first, self.second)

    def test_rejects_rebuilt_base(self):
        self.write(
            [_entry(verify_cache.BASE), _entry(verify_cache.IMAGE)],
            [_entry(verify_cache.BASE), _entry(verify_cache.IMAGE)],
        )
        with self.assertRaisesRegex(SystemExit, "was executed again for a new version"):
            verify_cache.verify(self.first, self.second)

    def test_rejects_cached_finalization(self):
        self.write(
            [_entry(verify_cache.BASE), _entry(verify_cache.IMAGE)],
            [_entry(verify_cache.IMAGE, cache_hit=True)],
        )
        with self.assertRaisesRegex(SystemExit, "second build: expected one executed MkosiImage"):
            verify_cache.verify(self.first, self.second)

    def test_rejects_first_build_without_base(self):
        self.write([_entry(verify_cache.IMAGE)], [_entry(verify_cache.IMAGE)])
        with self.assertRaisesRegex(SystemExit, "first build: expected one executed MkosiBase"):
            verify_cache.verify(self.first, self.second)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
