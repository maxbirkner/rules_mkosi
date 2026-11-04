#!/usr/bin/python3
"""Verify that a new image version reuses the cached two-stage base."""

import pathlib
import sys

from execution_log import read_entries

BASE = ("MkosiBase", "//mkosi/tests:two_stage_base")
IMAGE = ("MkosiImage", "//mkosi/tests:two_stage_release")


def _executions(entries, key):
    return [entry for entry in entries if (entry.get("mnemonic"), entry.get("targetLabel")) == key]


def _executed(entries, key):
    return [entry for entry in _executions(entries, key) if entry.get("cacheHit") is False]


def _wall_time(entry):
    return (entry.get("metrics") or {}).get("totalTime") or entry.get("walltime") or "unknown"


def verify(first_path, second_path):
    """Requires both stages in the first build and only the finalization in the second one."""
    first = read_entries(first_path)
    second = read_entries(second_path)
    errors = []
    for build, entries, keys in (("first", first, (BASE, IMAGE)), ("second", second, (IMAGE,))):
        for key in keys:
            if len(_executed(entries, key)) != 1:
                errors.append("{} build: expected one executed {} {}".format(build, *key))
    if _executed(second, BASE):
        errors.append("second build: {} {} was executed again for a new version".format(*BASE))
    if errors:
        raise SystemExit("two-stage cache check failed:\n" + "\n".join(errors))
    base = _executed(first, BASE)[0]
    first_finalize = _executed(first, IMAGE)[0]
    finalize = _executed(second, IMAGE)[0]
    print(
        "the new version reused the cached base: base {}, first finalization {}, second finalization {}".format(
            _wall_time(base), _wall_time(first_finalize), _wall_time(finalize)
        )
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_two_stage_cache.py FIRST_LOG SECOND_LOG")
    verify(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
