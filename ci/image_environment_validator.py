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
_PYTHONPATH_IGNORING_OPTIONS = {"-E", "-I"}


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
REQUIRED = frozenset({"PATH", "PYTHONNOUSERSITE", "MKOSI_FORCE_USERNS_FALLBACK", "PYTHONPATH"})
# Release builds pin the host distribution and the timestamp together; tracer builds set none of them.
RELEASE = frozenset({"MKOSI_HOST_DISTRIBUTION", "MKOSI_HOST_RELEASE", "SOURCE_DATE_EPOCH"})


def _interpreter_options(arguments: Sequence[str]) -> list[str]:
    options = []
    for argument in arguments[1:]:
        if not argument.startswith("-"):
            break
        options.append(argument)
    return options


def environment_errors(action: Mapping[str, Any]) -> list[str]:
    """Returns every way in which an MkosiImage action's environment differs from the expectations."""
    environment = {variable["key"]: variable.get("value", "") for variable in action.get("environmentVariables", [])}
    errors = [f"missing {key}" for key in sorted(REQUIRED - environment.keys())]
    for key, value in sorted(environment.items()):
        if key not in EXPECTED:
            errors.append(f"unexpected {key}={value}")
        elif not EXPECTED[key](value):
            errors.append(f"invalid {key}={value}")
    release = RELEASE & environment.keys()
    if release and release != RELEASE:
        errors.append(f"incomplete release environment: {', '.join(sorted(release))}")
    ignoring = _PYTHONPATH_IGNORING_OPTIONS.intersection(_interpreter_options(action.get("arguments", [])))
    if ignoring:
        errors.append(f"interpreter options {', '.join(sorted(ignoring))} ignore PYTHONPATH")
    return errors


def graph_errors(graph: Mapping[str, Any]) -> list[str]:
    """Returns the environment errors of every MkosiImage action in an aquery graph, prefixed by its target."""
    labels = {target["id"]: target["label"] for target in graph.get("targets", [])}
    actions = [action for action in graph.get("actions", []) if action.get("mnemonic") == "MkosiImage"]
    if not actions:
        return ["no MkosiImage action in the graph"]
    return [
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
