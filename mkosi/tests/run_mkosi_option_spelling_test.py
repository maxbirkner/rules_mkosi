"""run_mkosi.py recognizes mkosi options in every spelling that mkosi's argument parser accepts."""

import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest

RUN_MKOSI = pathlib.Path(sys.argv[1]).resolve()
MKOSI_ROOT = pathlib.Path(sys.argv[2]).resolve().parents[1]

# The configuration directory spellings that mkosi's argument parser accepts, with a {} placeholder for the path.
DIRECTORY_SPELLINGS = (
    ("-C", "{}"),
    ("-C{}",),
    ("-C={}",),
    ("--directory", "{}"),
    ("--directory={}",),
    ("-fC", "{}"),
    ("-fC{}",),
    ("-fC={}",),
)


def _load_run_mkosi():
    sys.path.insert(0, os.fspath(MKOSI_ROOT))
    spec = importlib.util.spec_from_file_location("run_mkosi", RUN_MKOSI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spell(spelling, path):
    return [argument.format(path) for argument in spelling]


class OptionSpellingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_mkosi = _load_run_mkosi()
        cls.command_line = cls.run_mkosi.command_line
        import mkosi.config

        cls.mkosi_config = mkosi.config

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name).resolve()

    def _mkosi_parse(self, arguments):
        return self.mkosi_config.create_argument_parser(chdir=False).parse_args(arguments)

    def test_configuration_directory_spellings_match_mkosi(self):
        for spelling in DIRECTORY_SPELLINGS:
            with self.subTest(spelling=spelling):
                arguments = _spell(spelling, "/config") + ["build"]
                self.assertEqual("/config", self._mkosi_parse(arguments).directory)
                self.assertEqual("/config", self.command_line.configuration_directory(arguments).value)

    def test_edge_case_values_match_mkosi(self):
        # Values that look like negative numbers, and empty values attached to grouped flags.
        for arguments, expected in (
            (["-C", "-5x", "build"], "-5x"),
            (["--directory", "-.5", "build"], "-.5"),
            (["-fC=", "build"], ""),
            (["-C=", "build"], ""),
        ):
            with self.subTest(arguments=arguments):
                parsed = self._mkosi_parse(arguments)
                self.assertEqual((expected, "build"), (parsed.directory, parsed.verb.value))
                self.assertEqual(expected, self.command_line.configuration_directory(arguments).value)
        argv = ["--kernel-preflight", "p", "--", "--output-dir", "-5x", "build"]
        self.assertEqual("-5x", self.command_line.mkosi_option_value(argv, "-O"))
        with self.assertRaisesRegex(SystemExit, "mkosi path option is missing its value"):
            self.command_line.configuration_directory(["-C", "-x", "build"])

    def test_last_configuration_directory_wins_like_mkosi(self):
        arguments = ["-C", "/first", "--directory=/second", "build"]
        self.assertEqual("/second", self._mkosi_parse(arguments).directory)
        self.assertEqual("/second", self.command_line.configuration_directory(arguments).value)

    def test_arguments_that_are_not_the_configuration_directory(self):
        for arguments in (
            ["build"],
            ["--dir", "/config"],
            ["--directory-extra=/config"],
            ["--environment=-C/config"],
            ["build", "--", "-C", "/config"],
        ):
            with self.subTest(arguments=arguments):
                self.assertIsNone(self.command_line.configuration_directory(arguments))
        self.assertIsNone(self.run_mkosi._stage_configuration(self.command_line.Preamble(), ["build"]))

    def test_every_directory_spelling_is_staged(self):
        configuration = self.root / "config"
        configuration.mkdir()
        (configuration / "mkosi.conf").write_text("[Content]\nBootable=yes\n")
        workspace = self.root / "workspace"
        for spelling in DIRECTORY_SPELLINGS:
            for include in (["-I", "{}/mkosi.conf"], ["--include={}/mkosi.conf"], ["-I{}/mkosi.conf"]):
                with self.subTest(spelling=spelling, include=include):
                    arguments = _spell(spelling, configuration) + _spell(include, configuration)
                    arguments += ["--workspace-directory=" + os.fspath(workspace), "build"]
                    staged = self.run_mkosi._stage_configuration(self.command_line.Preamble(), arguments)
                    self.assertEqual(workspace / "staging-root", staged)
                    self.assertEqual((staged / "mkosi.conf").read_text(), "[Content]\nBootable=yes\n")
                    expected = _spell(spelling, staged) + _spell(include, staged)
                    self.assertEqual(expected, arguments[: len(expected)])
                    self.assertNotIn(os.fspath(configuration), " ".join(arguments))

    def test_path_option_spellings_are_declared(self):
        for arguments in (
            ["--base-tree", "/base"],
            ["--base-tree=/base"],
            ["-O", "/base"],
            ["-O/base"],
            ["-O=/base"],
            ["--output-directory=/base"],
            ["--output-dir", "/base"],
            ["-fO/base"],
            ["--extra-tree=/base:/usr/share/target"],
            ["--sandbox-tree", "/base"],
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(["/base"], self.command_line.declared_paths(arguments + ["build"]))
        self.assertEqual(["/a", "/b", "/c"], self.command_line.declared_paths(["--include=/a,/b", "-I", "/c"]))

    def test_constants_resets_and_other_options_are_not_declared(self):
        for arguments in (
            ["--initrd=default", "--initrd", "default"],
            ["--tools-tree=default"],
            ["-I", "mkosi-initrd", "--include=mkosi-vm"],
            ["--initrd=", "--build-sources="],
            ["--environment=/base", "--output=image", "--image-id=/base", "--format", "disk"],
            ["build", "--", "--base-tree", "/base"],
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual([], self.command_line.declared_paths(arguments))

    def test_path_option_without_value_is_rejected(self):
        for arguments in (["--sandbox-tree"], ["--base-tree", "--format=disk"], ["-O"], ["-C"]):
            with (
                self.subTest(arguments=arguments),
                self.assertRaisesRegex(SystemExit, "mkosi path option is missing its value"),
            ):
                self.command_line.declared_paths(arguments)

    def test_relative_paths_become_absolute_in_every_spelling(self):
        for arguments, expected in (
            (
                ["--include=config", "--format=disk", "build"],
                ["--include=" + os.path.abspath("config"), "--format=disk"],
            ),
            (["-Iconfig"], ["-I" + os.path.abspath("config")]),
            (["-O=out"], ["-O=" + os.path.abspath("out")]),
            (["-fO", "out"], ["-fO", os.path.abspath("out")]),
            (["--repart-dir=parts"], ["--repart-dir=" + os.path.abspath("parts")]),
            (["--extra-tree=tree:/target"], ["--extra-tree=" + os.path.abspath("tree") + ":/target"]),
            (["--include=a,b"], ["--include=" + os.path.abspath("a") + "," + os.path.abspath("b")]),
            (["--tools-tree=default", "--initrd="], ["--tools-tree=default", "--initrd="]),
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(expected, self.command_line.absolute_paths(arguments)[: len(expected)])

    def test_output_directory_spellings_match_mkosi(self):
        for spelling in (("-O", "{}"), ("-O{}",), ("-O={}",), ("--output-directory={}",), ("--output-dir", "{}")):
            with self.subTest(spelling=spelling):
                arguments = _spell(spelling, self.root / "out") + ["build"]
                value = self.command_line.mkosi_option_value(["--kernel-preflight", "p", "--"] + arguments, "-O")
                self.assertEqual(self._mkosi_parse(arguments).output_dir, pathlib.Path(value))

    def test_workspace_and_tools_tree_spellings(self):
        arguments = ["--workspace-directory=/work", "--tools-tree", "/work/debian-tools"]
        self.assertEqual(pathlib.Path("/work"), self.run_mkosi._workspace(arguments))
        self.assertEqual("/work/debian-tools", self.command_line.value_after(arguments, "--tools-tree"))
        self.assertEqual(pathlib.Path("/work"), self.run_mkosi._workspace(["--workspace-dir", "/work"]))

    def test_release_parent_is_requested_only_by_run_mkosi_options(self):
        requests = self.run_mkosi._requests_release_parent
        self.assertTrue(requests(["--kernel-preflight", "p", "--release-base-tree", "/base", "--", "build"]))
        self.assertTrue(requests(["--debian-snapshot-repository", "/repository", "--", "build"]))
        self.assertFalse(requests(["--kernel-preflight", "p", "--", "--release-base-tree", "/base", "build"]))
        self.assertFalse(requests(["--kernel-preflight", "p", "--", "--debian-snapshot-repository", "/repository"]))
        self.assertFalse(requests(["--executable-path", "--release-base-tree", "--", "build"]))

    def test_path_options_are_read_from_mkosi(self):
        table = self.run_mkosi._package.mkosi_options.option_table()
        # The options that rules_mkosi passes to mkosi must be recognized as paths in every spelling.
        for spelling in (
            "-C",
            "--directory",
            "-I",
            "--include",
            "-O",
            "--output-directory",
            "--output-dir",
            "--tools-tree",
            "--extra-search-path",
            "--workspace-directory",
            "--cache-directory",
            "--package-cache-directory",
            "--build-directory",
            "--sandbox-tree",
            "--repart-directory",
            "--base-tree",
            "--initrd",
        ):
            with self.subTest(spelling=spelling):
                self.assertIsNotNone(table[spelling].path)
        self.assertIn("default", table["--initrd"].constants)
        self.assertIn("default", table["--tools-tree"].constants)
        self.assertIn("mkosi-initrd", table["-I"].constants)
        self.assertEqual("tree", table["--extra-tree"].path)
        for spelling in ("--output", "--image-id", "--environment", "--format", "-f", "--debug"):
            with self.subTest(spelling=spelling):
                self.assertIsNone(table[spelling].path)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
