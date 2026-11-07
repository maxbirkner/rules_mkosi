"""Tests for action-graph executable and environment validation."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from action_graph_validator import action_identity, audit, validate_action_environment


class ActionIdentityTest(unittest.TestCase):
    def test_distinguishes_actions_sharing_an_action_key(self):
        launcher = {"actionKey": "symlink", "mnemonic": "ExecutableSymlink", "outputIds": [7]}
        header = {"actionKey": "symlink", "mnemonic": "Symlink", "outputIds": [3]}

        self.assertNotEqual(action_identity(launcher), action_identity(header))

    def test_ignores_output_order(self):
        self.assertEqual(
            action_identity({"outputIds": [2, 1]}),
            action_identity({"outputIds": [1, 2]}),
        )

    def test_rejects_action_without_outputs(self):
        with self.assertRaisesRegex(ValueError, "without outputs.*Middleman"):
            action_identity({"mnemonic": "Middleman", "outputIds": []})


class ActionGraphValidatorTest(unittest.TestCase):
    def action(self, executable, mnemonic="CppCompile"):
        return {
            "mnemonic": mnemonic,
            "arguments": [executable, "-c", "source.cc"],
            "environmentVariables": [
                {"key": "PATH", "value": "/bin:/usr/bin:/usr/local/bin"},
            ],
        }

    def test_rejects_host_tool_basename_with_nonempty_path(self):
        with self.assertRaisesRegex(ValueError, "host-tool basename.*gcc"):
            validate_action_environment(self.action("gcc"), {"source.cc"})

    def test_accepts_declared_hermetic_compiler(self):
        executable = _COMPILER
        validate_action_environment(
            self.action(executable),
            {executable, "source.cc"},
        )

    def test_accepts_declared_hermetic_archiver(self):
        executable = "external/llvm++llvm_toolchain_minimal+llvm-toolchain-minimal-linux-amd64/bin/llvm-ar"
        validate_action_environment(
            self.action(executable, mnemonic="CppArchive"),
            {executable, "source.cc"},
        )

    def test_accepts_declared_python_zipper(self):
        executable = "external/bazel_tools/tools/zip/zipper/zipper"
        validate_action_environment(
            self.action(executable, mnemonic="PythonZipper"),
            {executable, "source.cc"},
        )

    def test_rejects_undeclared_executable(self):
        with self.assertRaisesRegex(ValueError, "not a declared input"):
            validate_action_environment(
                self.action("external/llvm/bin/clang++"),
                {"source.cc"},
            )


_COMPILER = "external/llvm++llvm_toolchain_minimal+llvm-toolchain-minimal-linux-amd64/bin/clang++"
_GLIBC_OBJECTS = "bazel-out/k8-opt-exec/bin/external/llvm++glibc+glibc_x86_64-linux-gnu.2.28"
_GLIBC_COPY = ["/bin/bash", "-c", 'cp -f "$1" "$2"', ""]
_PYTHON = "external/+debian_tools+mkosi_debian_python/python"
_OBJECT = "bazel-out/k8-fastbuild/bin/external/+debian_tools+mkosi_debian_tools/_objs/launcher_main.o"


def _action(mnemonic, arguments=(), inputs=(), outputs=()):
    return {"mnemonic": mnemonic, "arguments": list(arguments), "inputs": inputs, "outputs": outputs}


def _managed_actions():
    """Returns a minimal graph of the actions that build the Debian tools archive and launcher."""
    return [
        _action(
            "CppCompile",
            [_COMPILER, "-c", "mkosi/debian/launcher_main.cc"],
            [_COMPILER, "mkosi/debian/x.cc"],
            [_OBJECT],
        ),
        _action("CppLink", [_COMPILER, "-o", "launcher"], [_COMPILER, _OBJECT], ["bazel-out/launcher"]),
        _action("BuildDebianToolsArchive", [_PYTHON, "package_archive.py"], [_PYTHON], ["bazel-out/flat.tar"]),
        _action("CcStrip", [_COMPILER, "-o", "launcher.stripped"], [_COMPILER], ["bazel-out/launcher.stripped"]),
        _action("CppModuleMap", outputs=["bazel-out/launcher.cppmap"]),
        _action("CcStage0Compile", [_COMPILER, "-c", "start.S"], [_COMPILER], [f"{_GLIBC_OBJECTS}/Scrt1.o"]),
        _action(
            "CopyFile",
            [*_GLIBC_COPY, f"{_GLIBC_OBJECTS}/Scrt1.o", f"{_GLIBC_OBJECTS}/crt1.o"],
            [f"{_GLIBC_OBJECTS}/Scrt1.o"],
            [f"{_GLIBC_OBJECTS}/crt1.o"],
        ),
        _action("FileWrite", outputs=["bazel-out/launcher_config.json"]),
    ]


def _graph(actions):
    """Encodes actions with input and output paths as a jsonproto aquery graph."""
    ids = {}

    def artifact_id(path):
        return ids.setdefault(path, len(ids) + 1)

    graph_actions = []
    dep_sets = []
    for action in actions:
        dep_sets.append(
            {"id": len(dep_sets) + 1, "directArtifactIds": [artifact_id(path) for path in action["inputs"]]}
        )
        encoded = {key: value for key, value in action.items() if key not in ("inputs", "outputs")}
        encoded["inputDepSetIds"] = [len(dep_sets)]
        encoded["outputIds"] = [artifact_id(path) for path in action["outputs"]]
        graph_actions.append(encoded)
    return {
        "actions": graph_actions,
        "artifacts": [{"id": i, "pathFragmentId": i} for i in ids.values()],
        "pathFragments": [{"id": i, "label": path} for path, i in ids.items()],
        "depSetOfFiles": dep_sets,
    }


class AuditTest(unittest.TestCase):
    def test_accepts_managed_actions(self):
        counts = audit(_graph(_managed_actions()))
        self.assertEqual(counts["CppCompile"], 1)
        self.assertEqual(counts["CcStrip"], 1)
        self.assertEqual(counts["CopyFile"], 1)

    def test_rejects_injected_host_helpers(self):
        cases = [
            ("unmodeled action mnemonic: Genrule", "Genrule", ["/bin/bash", "-c", "tar cf $@"], []),
            ("unexpected executable for CppCompile", "CppCompile", ["/usr/bin/gcc"], ["/usr/bin/gcc"]),
            ("not a declared input: CppLink", "CppLink", [_COMPILER, "-o", "z"], [_OBJECT]),
            ("in-process action starts a process", "FileWrite", ["external/bazel_tools/sh"], []),
            ("unexpected executable for CopyFile", "CopyFile", [*_GLIBC_COPY, "mkosi/a", "bazel-out/b"], []),
            ("unexpected executable for CopyFile", "CopyFile", ["/bin/bash", "-c", "tar cf $2 $1", "", "a", "b"], []),
            ("host path in arguments", "CppCompile", [_COMPILER, "-I/usr/include"], [_COMPILER]),
            ("host path in arguments", "CppCompile", [_COMPILER, "--sysroot=/"], [_COMPILER]),
            ("host toolchain input", "CppLink", [_COMPILER], [_COMPILER, "external/local_config_cc/ld"]),
            ("unmanaged repository", "CppLink", [_COMPILER], [_COMPILER, "external/host_tools/tar"]),
            ("unproduced bazel-out input", "CppLink", [_COMPILER], [_COMPILER, "bazel-out/stale.o"]),
        ]
        for message, mnemonic, arguments, inputs in cases:
            injected = _action(mnemonic, arguments, inputs, ["bazel-out/injected"])
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                audit(_graph([*_managed_actions(), injected]))

    def test_rejects_graph_without_the_archive_action(self):
        actions = [action for action in _managed_actions() if action["mnemonic"] != "BuildDebianToolsArchive"]
        with self.assertRaisesRegex(ValueError, "required actions are missing: BuildDebianToolsArchive"):
            audit(_graph(actions))


if __name__ == "__main__":
    unittest.main()
