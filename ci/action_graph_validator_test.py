"""Tests for action-graph executable and environment validation."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from action_graph_validator import action_identity, validate_action_environment


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

    def test_accepts_declared_hermetic_zig_tool(self):
        executable = (
            "external/hermetic_cc_toolchain++toolchains+zig_config/"
            "tools/x86_64-linux-musl/c++"
        )
        validate_action_environment(
            self.action(executable),
            {executable, "source.cc"},
        )

    def test_accepts_declared_hermetic_archiver(self):
        executable = (
            "external/hermetic_cc_toolchain++toolchains+zig_config/"
            "tools/x86_64-linux-musl/ar"
        )
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
                self.action("external/zig/tools/c++"),
                {"source.cc"},
            )


if __name__ == "__main__":
    unittest.main()
