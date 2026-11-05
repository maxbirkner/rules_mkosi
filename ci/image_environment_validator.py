"""Validates the environment of mkosi image actions in a Bazel `aquery --output=jsonproto` graph.

Every variable needs an expectation in `EXPECTED`, so a new variable, such as one that depends on the build host, fails
the audit until it gets one.
"""

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

_EXECROOT_PREFIXES = ("external/", "bazel-out/")
# Interpreter options that make Python ignore PYTHONPATH.
_PYTHONPATH_IGNORING_OPTIONS = frozenset("EI")


def _is_execroot_path_list(value: str) -> bool:
    entries = value.split(":")
    return all(entry.startswith(_EXECROOT_PREFIXES) and ".." not in entry.split("/") for entry in entries)


EXPECTED: dict[str, Callable[[str], bool]] = {
    # No host program can be resolved.
    "PATH": lambda value: value == "",
    "PYTHONNOUSERSITE": lambda value: value == "1",
    # Namespaces come from the unprivileged fallback that kernel_preflight checks, not from the host's nsresourced.
    "MKOSI_FORCE_USERNS_FALLBACK": lambda value: value == "1",
    # mkosi and its modules are imported from declared inputs only.
    "PYTHONPATH": _is_execroot_path_list,
    "MKOSI_HOST_DISTRIBUTION": str.isalnum,
    "MKOSI_HOST_RELEASE": str.isalnum,
    "SOURCE_DATE_EPOCH": str.isdigit,
}
# Every image action sets these.
REQUIRED = frozenset({"PATH", "PYTHONNOUSERSITE", "MKOSI_FORCE_USERNS_FALLBACK", "PYTHONPATH"})
# Release actions pin the host distribution and the timestamp; tracer actions set none of them.
RELEASE = frozenset({"MKOSI_HOST_DISTRIBUTION", "MKOSI_HOST_RELEASE", "SOURCE_DATE_EPOCH"})
# Short interpreter options whose value follows, attached or as the next argument.
_VALUE_OPTIONS = frozenset("WX")
# Short interpreter options that end the interpreter options and start the program.
_PROGRAM_OPTIONS = frozenset("cm")
_VALUE_LONG_OPTIONS = frozenset({"--check-hash-based-pycs"})


def is_release(action: Mapping[str, Any]) -> bool:
    """Returns whether an action is a hermetic release build, the only kind of image build that may be cached."""
    return all(entry.get("key") != "no-cache" for entry in action.get("executionInfo", []))


def _scan_short_options(cluster: str) -> tuple[set[str], bool, bool]:
    """Scans a short option cluster such as `sI` from `-sI`.

    Returns:
        The option letters before any option value, whether the next argument is an option value, and whether the
        cluster starts the program.
    """
    letters = set()
    for index, letter in enumerate(cluster):
        letters.add(letter)
        if letter in _PROGRAM_OPTIONS:
            return letters, False, True
        if letter in _VALUE_OPTIONS:
            return letters, index == len(cluster) - 1, False
    return letters, False, False


def interpreter_flags(arguments: Sequence[str]) -> set[str]:
    """Returns the short option letters that a Python command line passes to the interpreter itself."""
    flags: set[str] = set()
    expects_value = False
    for argument in arguments[1:]:
        if expects_value:
            expects_value = False
            continue
        if argument in ("-", "--") or not argument.startswith("-"):
            break
        if argument.startswith("--"):
            expects_value = argument in _VALUE_LONG_OPTIONS
            continue
        letters, expects_value, starts_program = _scan_short_options(argument[1:])
        flags |= letters
        if starts_program:
            break
    return flags


def environment_errors(action: Mapping[str, Any]) -> list[str]:
    """Returns every way in which an MkosiImage action's environment differs from the expectations."""
    environment = {variable["key"]: variable.get("value", "") for variable in action.get("environmentVariables", [])}
    release = is_release(action)
    required = REQUIRED | RELEASE if release else REQUIRED
    allowed = EXPECTED.keys() if release else EXPECTED.keys() - RELEASE
    errors = [f"missing {key}" for key in sorted(required - environment.keys())]
    for key, value in sorted(environment.items()):
        if key not in allowed:
            errors.append(f"unexpected {key}={value}")
        elif not EXPECTED[key](value):
            errors.append(f"invalid {key}={value}")
    ignoring = _PYTHONPATH_IGNORING_OPTIONS & interpreter_flags(action.get("arguments", []))
    if ignoring:
        errors.append(f"interpreter options {', '.join('-' + flag for flag in sorted(ignoring))} ignore PYTHONPATH")
    return errors


def graph_errors(graph: Mapping[str, Any]) -> list[str]:
    """Returns the environment errors of every MkosiImage action in an aquery graph, prefixed by its target.

    The graph must contain at least one release and one tracer action, so that both expectations are checked.
    """
    labels = {target["id"]: target["label"] for target in graph.get("targets", [])}
    actions = [action for action in graph.get("actions", []) if action.get("mnemonic") == "MkosiImage"]
    kinds = {is_release(action) for action in actions}
    errors = []
    for kind, release in (("release", True), ("tracer", False)):
        if release not in kinds:
            errors.append(f"no {kind} MkosiImage action in the graph")
    return errors + [
        f"{labels.get(action.get('targetId'), '<unknown target>')}: {error}"
        for action in actions
        for error in environment_errors(action)
    ]


def main(argv: Sequence[str]) -> int:
    """Validates the aquery jsonproto file named by the only argument."""
    if len(argv) != 2:
        print(f"usage: {argv[0]} AQUERY_JSONPROTO", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as file:
        errors = graph_errors(json.load(file))
    for error in errors:
        print(f"mkosi image action environment: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
