"""Audit the jsonproto aquery graph of the Debian tools launcher for host dependencies.

Usage: action_graph_validator.py GRAPH.json, where GRAPH.json is
`bazel aquery --output=jsonproto 'deps(@mkosi_debian_tools//:launcher)'`. The launcher's graph contains every action
that builds the Debian tools archive, the launcher, and the namespace runner.
"""

import json
import pathlib
import re
import sys

_FIXED_ZIG_PATH = "/bin:/usr/bin:/usr/local/bin"
_HOST_TOOL_BASENAMES = {
    "ar",
    "bash",
    "cc",
    "clang",
    "gcc",
    "ld",
    "sh",
    "strip",
}
_HERMETIC_PATH_ACTIONS = {
    "CppArchive",
    "CppCompile",
    "CppLink",
    "PythonZipper",
}


def action_identity(action):
    """Return a key that distinguishes every action in an aquery graph.

    Bazel derives `actionKey` from an action's behavior rather than its artifacts, so distinct actions such as two
    symlinks share a key. Each artifact has exactly one generating action, so the output artifact IDs identify it.

    Raises:
        ValueError: If the action declares no outputs and therefore cannot be identified.
    """
    outputs = action.get("outputIds", [])
    if not outputs:
        raise ValueError(f"action without outputs: {action.get('mnemonic')}")
    return tuple(sorted(outputs))


def validate_action_environment(action, input_paths):
    """Reject host-resolved executables exposed through action environments."""
    mnemonic = action["mnemonic"]
    arguments = action.get("arguments", [])
    for variable in action.get("environmentVariables", []):
        key = variable.get("key", "")
        value = variable.get("value", "")
        if not value or value == "/proc/self/cwd":
            continue
        if key == "PATH" and value == _FIXED_ZIG_PATH:
            if mnemonic == "CcStrip" and arguments[:1] == ["/usr/bin/false"]:
                continue
            if mnemonic not in _HERMETIC_PATH_ACTIONS or not arguments:
                raise ValueError(f"nonempty PATH on unsupported action: {mnemonic}")
            executable = arguments[0]
            basename = pathlib.PurePosixPath(executable).name
            if "/" not in executable and basename in _HOST_TOOL_BASENAMES:
                raise ValueError(f"host-tool basename exposed through PATH: {basename}")
            if executable not in input_paths:
                raise ValueError(f"PATH executable is not a declared input: {executable}")
            continue
        if value.startswith("/"):
            raise ValueError(f"host environment path: {mnemonic} {key}={value}")


# Actions that Bazel performs itself without starting a process. Middleman is Bazel 8's name for Bazel 9's RunfilesTree.
_IN_PROCESS_ACTIONS = frozenset(
    {
        "ExecutableSymlink",
        "FileWrite",
        "Middleman",
        "RepoMappingManifest",
        "RunfilesTree",
        "SolibSymlink",
        "SourceSymlinkManifest",
        "Symlink",
        "SymlinkTree",
        "TemplateExpand",
        "TranslateBuildInfo",
        "UnresolvedSymlink",
    }
)
_ZIG_TOOLS = "external/hermetic_cc_toolchain++toolchains+zig_config/tools/"
# The in-build executable that each process action must run, as a path prefix.
_SPAWN_EXECUTABLES = {
    "BuildDebianToolsArchive": "external/+debian_tools+mkosi_debian_python/python",
    "CppArchive": _ZIG_TOOLS,
    "CppCompile": _ZIG_TOOLS,
    "CppLink": _ZIG_TOOLS,
    "PyCompile": "external/rules_python++python+python_3_",
    "PythonZipper": "external/bazel_tools/tools/zip/zipper/zipper",
}
# The static toolchain disables stripping, but Bazel still declares CcStrip with a placeholder executable. The
# bootstrap-determinism CI job fails if a build ever executes it.
_DISABLED_ACTIONS = {"CcStrip": "/usr/bin/false"}
_REQUIRED_ACTIONS = ("BuildDebianToolsArchive", "CppCompile", "CppLink")
_INPUT_REPOSITORIES = ("bazel_tools", "hermetic_cc_toolchain", "rules_cc+", "rules_python+", "+debian_tools+")
_STATUS_FILES = ("volatile-status.txt", "stable-status.txt")
# An absolute path as the whole argument, a flag value such as --sysroot=/usr, a list item, or a short-flag suffix.
_ABSOLUTE_PATH = re.compile(r"(?:^|[=:,]|^-[A-Za-z]+)/")
_HOST_TOKENS = (
    "/bin/bash",
    "/usr/bin/gcc",
    "/usr/bin/clang",
    "/usr/bin/ar",
    "/usr/bin/ld",
    "/usr/bin/strip",
    "local_config_cc",
)


class ActionGraph:
    """Resolves the artifact paths, inputs, and producing actions of a jsonproto aquery graph."""

    def __init__(self, graph):
        self.actions = graph.get("actions", [])
        fragments = {fragment["id"]: fragment for fragment in graph.get("pathFragments", [])}
        self.paths = {
            artifact["id"]: self._path(fragments, artifact["pathFragmentId"]) for artifact in graph.get("artifacts", [])
        }
        self.dep_sets = {dep_set["id"]: dep_set for dep_set in graph.get("depSetOfFiles", [])}
        self.producers = {artifact: action for action in self.actions for artifact in action.get("outputIds", [])}

    @staticmethod
    def _path(fragments, fragment_id):
        parts = []
        while fragment_id:
            fragment = fragments[fragment_id]
            parts.append(fragment["label"])
            fragment_id = fragment.get("parentId")
        return "/".join(reversed(parts))

    def input_ids(self, action):
        """Returns the IDs of every artifact in the transitive input dep sets of action."""
        artifacts = set()
        pending = list(action.get("inputDepSetIds", []))
        seen = set()
        while pending:
            dep_set_id = pending.pop()
            if dep_set_id in seen:
                continue
            seen.add(dep_set_id)
            dep_set = self.dep_sets[dep_set_id]
            artifacts.update(dep_set.get("directArtifactIds", []))
            pending.extend(dep_set.get("transitiveDepSetIds", []))
        return artifacts


def validate_executable(action, input_paths):
    """Rejects an action whose mnemonic is not modeled or whose process is not its declared in-build executable."""
    mnemonic = action.get("mnemonic")
    arguments = action.get("arguments", [])
    if mnemonic in _IN_PROCESS_ACTIONS:
        if arguments:
            raise ValueError(f"in-process action starts a process: {mnemonic} {arguments[0]}")
        return
    if mnemonic in _DISABLED_ACTIONS:
        if arguments[:1] != [_DISABLED_ACTIONS[mnemonic]]:
            raise ValueError(f"disabled action has an unexpected executable: {mnemonic} {arguments[:1]}")
        return
    if mnemonic not in _SPAWN_EXECUTABLES:
        raise ValueError(f"unmodeled action mnemonic: {mnemonic} {arguments[:1]}")
    executable = arguments[0] if arguments else ""
    if not executable.startswith(_SPAWN_EXECUTABLES[mnemonic]):
        raise ValueError(f"unexpected executable for {mnemonic}: {executable}")
    if executable not in input_paths:
        raise ValueError(f"executable is not a declared input: {mnemonic} {executable}")


def validate_arguments(action):
    """Rejects absolute paths and host toolchain names in the arguments of an action."""
    mnemonic = action.get("mnemonic")
    arguments = action.get("arguments", [])
    if mnemonic in _DISABLED_ACTIONS:
        arguments = arguments[1:]
    for token in arguments:
        if _ABSOLUTE_PATH.search(token) or any(host in token for host in _HOST_TOKENS):
            raise ValueError(f"host path in arguments: {mnemonic} {token}")


def validate_inputs(graph, action):
    """Rejects inputs outside the managed repositories and bazel-out inputs that no action in the graph produces."""
    mnemonic = action.get("mnemonic")
    for artifact_id in graph.input_ids(action):
        path = graph.paths[artifact_id]
        if any(host in path for host in _HOST_TOKENS):
            raise ValueError(f"host toolchain input: {mnemonic} {path}")
        if path.startswith("bazel-out/"):
            if artifact_id not in graph.producers and not path.endswith(_STATUS_FILES):
                raise ValueError(f"unproduced bazel-out input: {mnemonic} {path}")
        elif path.startswith("external/"):
            if not path.split("/", 2)[1].startswith(_INPUT_REPOSITORIES):
                raise ValueError(f"input from an unmanaged repository: {mnemonic} {path}")
        elif not path.startswith("mkosi/"):
            raise ValueError(f"input outside the managed roots: {mnemonic} {path}")


def audit(graph_json):
    """Validates every action of the graph and returns the number of actions per mnemonic.

    Raises:
        ValueError: If an action is unmodeled or depends on the host, or a required action is missing.
    """
    graph = ActionGraph(graph_json)
    counts = {}
    for action in graph.actions:
        action_identity(action)
        input_paths = {graph.paths[artifact_id] for artifact_id in graph.input_ids(action)}
        validate_executable(action, input_paths)
        validate_arguments(action)
        validate_action_environment(action, input_paths)
        validate_inputs(graph, action)
        counts[action["mnemonic"]] = counts.get(action["mnemonic"], 0) + 1
    missing = [mnemonic for mnemonic in _REQUIRED_ACTIONS if mnemonic not in counts]
    if missing:
        raise ValueError(f"required actions are missing: {', '.join(missing)}")
    return counts


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: action_graph_validator.py GRAPH.json")
    with open(argv[1], encoding="utf-8") as graph_file:
        graph_json = json.load(graph_file)
    try:
        counts = audit(graph_json)
    except ValueError as error:
        raise SystemExit(f"Debian tools action graph audit failed: {error}") from error
    for mnemonic, count in sorted(counts.items()):
        print(f"{mnemonic}: {count}")
    print(f"Debian tools action graph: {sum(counts.values())} actions, all modeled and host-independent")


if __name__ == "__main__":
    main(sys.argv)
