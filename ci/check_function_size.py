#!/usr/bin/env python3
"""Fail when a Python or Starlark function exceeds a line limit.

Functions that were already too long are listed with their current length in a baseline file.
A listed function may shrink but never grow, and the baseline itself may only shrink: entries for
functions that were removed, fit the limit, or got shorter must be removed or lowered, and no entry may be added
or raised compared with the baseline committed at the base revision.
"""

import argparse
import ast
import os
import pathlib
import subprocess
import sys
from collections.abc import Iterable, Mapping

MAX_LINES = 40
BASELINE = pathlib.Path("ci/function_size_baseline.txt")
SOURCE_PATTERNS = ("*.py", "*.bzl")
# CI sets this to the pull request's base commit; without it the baseline is compared with the one at HEAD.
BASE_REF_ENVIRONMENT = "FUNCTION_SIZE_BASE_REF"
BASELINE_HEADER = """\
# Functions longer than the limit enforced by ci/check_function_size.py, with their current length.
# Entries may only be lowered or removed; run `python3 ci/check_function_size.py --update-baseline` after
# shortening a function. Format: <path>:<qualified function name> <lines>
"""


def function_lengths(source: str, filename: str) -> dict[str, int]:
    """Return the length of every function in a Python or Starlark source, keyed by qualified name.

    A length spans the `def` line through the last line of the body; decorators are not counted.
    Nested functions and methods are named `outer.inner` and `Class.method`; repeated names get a `#2` suffix.
    Starlark is parsed with the Python parser, which accepts the Starlark syntax used in `.bzl` files.

    Raises:
        SyntaxError: if the source does not parse.
    """
    lengths: dict[str, int] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                if not isinstance(child, ast.ClassDef):
                    key, count = name, 1
                    while key in lengths:
                        count += 1
                        key = "%s#%d" % (name, count)
                    lengths[key] = (child.end_lineno or child.lineno) - child.lineno + 1
                visit(child, name + ".")
            else:
                visit(child, prefix)

    visit(ast.parse(source, filename), "")
    return lengths


def collect_lengths(root: pathlib.Path, paths: Iterable[str]) -> dict[str, int]:
    """Return the length of every function in paths, relative to root, keyed by `path:qualified name`."""
    lengths = {}
    for path in paths:
        source = (root / path).read_text(encoding="utf-8")
        for name, length in function_lengths(source, path).items():
            lengths["%s:%s" % (path, name)] = length
    return lengths


def read_baseline(text: str) -> dict[str, int]:
    """Parse baseline lines of the form `<path>:<qualified name> <lines>`, skipping comments and blank lines.

    Raises:
        ValueError: if a line is malformed or an entry is repeated.
    """
    baseline: dict[str, int] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        key, _, length = line.rpartition(" ")
        if not key or not length.isdigit() or ":" not in key:
            raise ValueError("baseline line %d is not '<path>:<function> <lines>': %r" % (number, line))
        if key in baseline:
            raise ValueError("baseline line %d repeats %s" % (number, key))
        baseline[key] = int(length)
    return baseline


def format_baseline(baseline: Mapping[str, int]) -> str:
    """Render baseline entries sorted by key, preceded by the explanatory header."""
    return BASELINE_HEADER + "".join("%s %d\n" % (key, baseline[key]) for key in sorted(baseline))


def violations(lengths: Mapping[str, int], baseline: Mapping[str, int], max_lines: int) -> list[str]:
    """Return one message per function that is too long and per baseline entry that should shrink."""
    errors = []
    for key, length in sorted(lengths.items()):
        if key in baseline and length > baseline[key]:
            errors.append("%s: grew to %d lines; the baseline allows %d" % (key, length, baseline[key]))
        elif key not in baseline and length > max_lines:
            errors.append("%s: %d lines exceeds the %d-line limit" % (key, length, max_lines))
    for key, allowed in sorted(baseline.items()):
        current = lengths.get(key)
        if current is None:
            errors.append("%s: function no longer exists; remove its baseline entry" % key)
        elif current <= max_lines:
            errors.append("%s: now %d lines and within the limit; remove its baseline entry" % (key, current))
        elif current < allowed:
            errors.append("%s: shrank to %d lines; lower its baseline entry from %d" % (key, current, allowed))
    return errors


def ratchet_violations(baseline: Mapping[str, int], base_baseline: Mapping[str, int]) -> list[str]:
    """Return one message per baseline entry that is missing from, or higher than in, the base revision's baseline."""
    errors = []
    for key, allowed in sorted(baseline.items()):
        if key not in base_baseline:
            errors.append("%s: new baseline entry; shorten the function instead of listing it" % key)
        elif allowed > base_baseline[key]:
            errors.append(
                "%s: baseline entry raised from %d to %d; entries may only shrink" % (key, base_baseline[key], allowed)
            )
    return errors


def shrunk_baseline(lengths: Mapping[str, int], baseline: Mapping[str, int], max_lines: int) -> dict[str, int]:
    """Return the baseline with stale entries removed and shrunk ones lowered; it never adds or raises entries."""
    return {
        key: min(allowed, lengths[key])
        for key, allowed in baseline.items()
        if key in lengths and lengths[key] > max_lines
    }


def tracked_sources(root: pathlib.Path) -> list[str]:
    """Return the Git-tracked Python and Starlark files below root."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", *SOURCE_PATTERNS],
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(path for path in result.stdout.split("\0") if path)


def _git(root: pathlib.Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True, text=True).stdout


def base_revision(root: pathlib.Path, base_ref: str | None) -> str:
    """Return the merge base of HEAD and base_ref, or HEAD when base_ref is empty.

    Raises:
        subprocess.CalledProcessError: if base_ref is unknown or shares no history with HEAD.
    """
    if not base_ref:
        return "HEAD"
    return _git(root, "merge-base", "HEAD", base_ref).strip()


def committed_baseline(root: pathlib.Path, revision: str, path: pathlib.Path) -> dict[str, int] | None:
    """Return the baseline file committed at revision, or None if revision has no such file.

    Raises:
        subprocess.CalledProcessError: if revision is not a commit.
    """
    _git(root, "rev-parse", "--verify", "--quiet", revision + "^{commit}")
    blob = "%s:%s" % (revision, path.as_posix())
    if subprocess.run(["git", "-C", str(root), "cat-file", "-e", blob], check=False, capture_output=True).returncode:
        return None
    return read_baseline(_git(root, "show", blob))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path())
    parser.add_argument("--baseline", type=pathlib.Path, default=BASELINE, help="relative to --root")
    parser.add_argument("--max-lines", type=int, default=MAX_LINES)
    parser.add_argument("--update-baseline", action="store_true", help="remove stale and lower shrunk entries")
    parser.add_argument(
        "--base-ref",
        default=os.environ.get(BASE_REF_ENVIRONMENT),
        help="compare the baseline with its version at the merge base with this ref instead of HEAD",
    )
    args = parser.parse_args(argv)

    baseline_path = args.root / args.baseline
    baseline = read_baseline(baseline_path.read_text(encoding="utf-8"))
    lengths = collect_lengths(args.root, tracked_sources(args.root))
    if args.update_baseline:
        baseline = shrunk_baseline(lengths, baseline, args.max_lines)
        baseline_path.write_text(format_baseline(baseline), encoding="utf-8")
    errors = violations(lengths, baseline, args.max_lines)
    base_baseline = committed_baseline(args.root, base_revision(args.root, args.base_ref), args.baseline)
    if base_baseline is not None:
        errors += ratchet_violations(baseline, base_baseline)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print("Split long functions into smaller ones; see ci/README.md.", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
