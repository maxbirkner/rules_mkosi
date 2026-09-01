"""Tests for action-graph executable and environment validation."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from action_graph_validator import validate_action_environment


class ActionGraphValidatorTest(unittest.TestCase):
    def action(self, executable):
        return {
            "mnemonic": "CppCompile",
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

    def test_rejects_undeclared_executable(self):
        with self.assertRaisesRegex(ValueError, "not a declared input"):
            validate_action_environment(
                self.action("external/zig/tools/c++"),
                {"source.cc"},
            )


if __name__ == "__main__":
    unittest.main()
