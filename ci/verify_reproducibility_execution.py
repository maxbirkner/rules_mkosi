#!/usr/bin/python3
"""Verify that a reproducibility build executed every subject action."""

import pathlib
import sys

from execution_log import read_entries

_DEBIAN_TOOLS = "@@+debian_tools+mkosi_debian_tools//"

SUBJECTS = {
    "release": {
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
    },
    "bootstrap": {
        ("BuildDebianToolsArchive", _DEBIAN_TOOLS + ":tree"),
        ("CppCompile", _DEBIAN_TOOLS + ":launcher_binary"),
        ("CppLink", _DEBIAN_TOOLS + ":launcher_binary"),
        ("CppCompile", _DEBIAN_TOOLS + ":namespace_runner_binary"),
        ("CppLink", _DEBIAN_TOOLS + ":namespace_runner_binary"),
        ("CppCompile", "//mkosi/private:write_all"),
        ("CppCompile", "@@rules_cc+//cc/runfiles:runfiles"),
    },
}

# Disabled toolchain actions, such as CcStrip, run this placeholder; a build must never execute it.
_PLACEHOLDER = "/usr/bin/false"


def verify(path, build_name, subject="release"):
    expected = SUBJECTS[subject]
    observed = {}
    errors = []
    for entry in read_entries(path):
        key = (entry.get("mnemonic"), entry.get("targetLabel"))
        if key in expected:
            observed.setdefault(key, []).append(entry)
        if _PLACEHOLDER in entry.get("commandArgs", []):
            errors.append("{} {}: executed the disabled-action placeholder {}".format(*key, _PLACEHOLDER))

    for key in sorted(expected):
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
    print("{} independently executed every {} action".format(build_name, subject))


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4) or sys.argv[3:] not in ([], ["release"], ["bootstrap"]):
        raise SystemExit("usage: verify_reproducibility_execution.py LOG BUILD_NAME [release|bootstrap]")
    verify(pathlib.Path(sys.argv[1]), sys.argv[2], *sys.argv[3:])
