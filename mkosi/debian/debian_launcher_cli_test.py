import importlib.util
import os
import pathlib
import unittest
from unittest import mock

from click.testing import CliRunner


_SPEC = importlib.util.spec_from_file_location(
    "debian_launcher",
    pathlib.Path(__file__).with_name("debian_launcher.py"),
)
debian_launcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(debian_launcher)


class DebianLauncherCliTest(unittest.TestCase):
    def test_tool_environment_preserves_only_determinism_controls(self):
        with mock.patch.dict(
            os.environ,
            {
                "HOST_SECRET": "excluded",
                "SOURCE_DATE_EPOCH": "0",
                "SYSTEMD_REPART_MKFS_OPTIONS_EXT4": "-E hash_seed=fixed",
            },
            clear=True,
        ):
            self.assertEqual(
                {
                    "HOME": "/root",
                    "PATH": "",
                    "SOURCE_DATE_EPOCH": "0",
                    "SYSTEMD_REPART_MKFS_OPTIONS_EXT4": "-E hash_seed=fixed",
                },
                debian_launcher._tool_environment(),
            )

    def test_help_is_a_successful_cli_operation(self):
        result = CliRunner().invoke(debian_launcher.cli, ["--help"])

        self.assertEqual(0, result.exit_code)
        self.assertIn("Usage: debian-launcher", result.stdout)
        self.assertIn("--validate-only", result.stdout)
        self.assertEqual("", result.stderr)

    def test_unknown_tool_is_a_usage_error(self):
        result = CliRunner().invoke(debian_launcher.cli, ["/usr/bin/not-mapped"])

        self.assertEqual(2, result.exit_code)
        self.assertIn("unknown or unmapped Debian tool", result.stderr)

    def test_missing_tool_is_a_usage_error(self):
        result = CliRunner().invoke(debian_launcher.cli)

        self.assertEqual(2, result.exit_code)
        self.assertIn("Missing argument 'TOOL'", result.stderr)

    def test_setup_error_keeps_the_launcher_contract(self):
        with mock.patch.object(
            debian_launcher,
            "_runtime_files",
            side_effect=RuntimeError("missing runtime"),
        ):
            result = CliRunner().invoke(debian_launcher.cli, ["/usr/bin/dpkg"])

        self.assertEqual(1, result.exit_code)
        self.assertEqual(
            "Debian launcher setup failed: missing runtime\n",
            result.stderr,
        )

    def test_tool_arguments_and_nonzero_status_are_forwarded_exactly(self):
        runtime = debian_launcher.RuntimeFiles(
            archive="tree.tar",
            archive_sha256="0" * 64,
            extractor="extract_tree.py",
            namespace_runner="namespace_runner",
        )
        with (
            mock.patch.object(debian_launcher, "_runtime_files", return_value=runtime),
            mock.patch.object(
                debian_launcher,
                "_extract_root",
                return_value="/scratch/root",
            ),
            mock.patch.object(debian_launcher, "_run", return_value=37) as run,
        ):
            result = CliRunner().invoke(
                debian_launcher.cli,
                ["/usr/bin/dpkg", "--version"],
            )

        self.assertEqual(37, result.exit_code)
        self.assertEqual(["--version"], run.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
