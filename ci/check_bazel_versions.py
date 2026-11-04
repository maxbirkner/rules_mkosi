"""Checks that every copy of the Bazel versions agrees with its source.

`.bazelversion` is the default Bazel version, which generates the lockfiles, and `ci/bazel_versions.json` lists every
version that CI tests; the lowest one is the supported minimum. The files in `COPIES` must repeat these versions, and
no other tracked file may name a tested version, so a Bazel bump only touches the sources and `COPIES`.
"""

import json
import pathlib
import re
import subprocess
import sys

DEFAULT_SOURCE = ".bazelversion"
TESTED_SOURCE = "ci/bazel_versions.json"
VERSION = re.compile(r"\d+\.\d+\.\d+")

# Each copy is a file, a pattern whose group captures one version, and the versions that all matches must list.
COPIES = (
    ("e2e/smoke/.bazelversion", r"\A(\S+)\n\Z", "default"),
    ("MODULE.bazel", r'">=\s*([\d.]*\d)"', "minimum"),
    ("README.md", r"The minimum is ([\d.]*\d)\.", "minimum"),
    (".bcr/presubmit.yml", r'^\s*bazel: "([^"]*)"$', "tested"),
)
# Files that name a Bazel version only as a past measurement or as test data.
UNRELATED = frozenset({"docs/starlark-coverage.md", "tools/bazel_wrapper_test.py"})


def version_key(version: str) -> tuple[int, ...]:
    """Returns a sort key that orders versions numerically."""
    return tuple(int(part) for part in version.split("."))


def load_versions(root: pathlib.Path) -> dict[str, list[str]]:
    """Reads the sources and returns the expected versions per role.

    Raises:
        ValueError: The sources are malformed or the default version is not tested.
    """
    default = (root / DEFAULT_SOURCE).read_text(encoding="utf-8").strip()
    tested = json.loads((root / TESTED_SOURCE).read_text(encoding="utf-8"))
    if not isinstance(tested, list) or not tested:
        raise ValueError(f"{TESTED_SOURCE} must be a non-empty list of versions")
    for version in [default, *tested]:
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            raise ValueError(f"not a Bazel version: {version!r}")
    if default not in tested:
        raise ValueError(f"{DEFAULT_SOURCE} version {default} is missing from {TESTED_SOURCE}")
    return {"default": [default], "minimum": [min(tested, key=version_key)], "tested": tested}


def check_copies(root: pathlib.Path, versions: dict[str, list[str]]) -> list[str]:
    """Returns an error for every file in `COPIES` whose versions differ from the sources."""
    errors = []
    for path, pattern, role in COPIES:
        text = (root / path).read_text(encoding="utf-8")
        actual = re.findall(pattern, text, flags=re.MULTILINE)
        if actual != versions[role]:
            errors.append(f"{path}: expected {role} Bazel versions {versions[role]}, found {actual}")
    return errors


def find_stray_copies(root: pathlib.Path, paths: list[str], tested: list[str]) -> list[str]:
    """Returns an error for every other file in `paths` that names one of the `tested` versions."""
    allowed = {DEFAULT_SOURCE, TESTED_SOURCE, *UNRELATED, *(path for path, _, _ in COPIES)}
    alternatives = b"|".join(re.escape(version.encode()) for version in tested)
    pattern = re.compile(rb"(?<![\w.])(?:" + alternatives + rb")(?!\w|\.\d)")
    errors = []
    for path in paths:
        file = root / path
        if path in allowed or file.is_symlink() or not file.is_file():
            continue
        if pattern.search(file.read_bytes()):
            errors.append(f"{path}: names a tested Bazel version; derive it from {DEFAULT_SOURCE} or {TESTED_SOURCE}")
    return errors


def main() -> int:
    """Checks the Git work tree in the current directory and reports every inconsistency."""
    root = pathlib.Path.cwd()
    listing = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True, text=True).stdout
    try:
        versions = load_versions(root)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    errors = check_copies(root, versions)
    errors += find_stray_copies(root, [path for path in listing.split("\0") if path], versions["tested"])
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
