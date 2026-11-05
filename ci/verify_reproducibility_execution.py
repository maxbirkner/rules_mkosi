#!/usr/bin/python3
"""Verify that a reproducibility build executed both subject actions."""

import pathlib
import sys

from execution_log import read_entries

EXPECTED = {
    ("MkosiImage", "//mkosi/tests:release_subject"),
    (
        "MkosiReproducibilityManifest",
        "//mkosi/tests:release_reproducibility",
    ),
    ("MkosiImage", "//mkosi/tests:erofs_release"),
    (
        "MkosiReproducibilityManifest",
        "//mkosi/tests:erofs_release_reproducibility",
    ),
    ("MkosiSysupdatePayload", "//mkosi/tests:erofs_release_payload"),
    ("MkosiBase", "//mkosi/tests:two_stage_base"),
    ("MkosiImage", "//mkosi/tests:two_stage_release"),
    (
        "MkosiReproducibilityManifest",
        "//mkosi/tests:two_stage_reproducibility",
    ),
}


def verify(path, build_name):
    observed = {}
    for entry in read_entries(path):
        key = (entry.get("mnemonic"), entry.get("targetLabel"))
        if key in EXPECTED:
            observed.setdefault(key, []).append(entry)

    errors = []
    for key in sorted(EXPECTED):
        entries = observed.get(key, [])
        if len(entries) != 1:
            errors.append("{} {}: expected one execution, found {}".format(*key, len(entries)))
        elif entries[0].get("cacheHit") is not False:
            errors.append("{} {}: action was satisfied from a cache".format(*key))
    if errors:
        raise SystemExit(
            "{} independence check failed:\n{}".format(
                build_name,
                "\n".join(errors),
            )
        )
    print("{} independently executed every image, base, and projection action".format(build_name))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_reproducibility_execution.py LOG BUILD_NAME")
    verify(pathlib.Path(sys.argv[1]), sys.argv[2])
