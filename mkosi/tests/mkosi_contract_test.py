"""The mkosi internals that release mode patches match the contract of the pinned mkosi toolchain."""

import ast
import dataclasses
import importlib.util
import os
import pathlib
import re
import sys
import tempfile
import types
import unittest

RUN_MKOSI = pathlib.Path(sys.argv[1]).resolve()
MKOSI_ROOT = pathlib.Path(sys.argv[2]).resolve().parents[1]
VERSIONS_BZL = pathlib.Path(sys.argv[3]).resolve()

# Strings in release_validation.py that are not mkosi Config field names.
_VALIDATION_WORDS = frozenset(
    (
        "always",
        "base",
        "bios",
        "finalize",
        "host",
        "main",
        "mkosi",
        "name",
        "no",
        "none",
        "source",
        "uefi",
        "value",
        "yes",
    )
)


_CALLERS = """
import mkosi
from mkosi import archive

make_tar = mkosi.make_tar


def global_caller(src, dst):
    make_tar(src, dst)


def nested_global_caller(src, dst):
    def archive_root():
        make_tar(src, dst)

    archive_root()


def attribute_caller(src, dst):
    archive.make_tar(src, dst)


def local_import_caller(src, dst):
    from mkosi.archive import make_tar

    make_tar(src, dst)
"""


def _load_runner():
    sys.path.insert(0, os.fspath(MKOSI_ROOT))
    spec = importlib.util.spec_from_file_location("run_mkosi", RUN_MKOSI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._package


class MkosiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = _load_runner()
        cls.contract = package.mkosi_contract
        cls.release_patches = package.release_patches
        cls.release_validation = package.release_validation
        import mkosi.config

        cls.mkosi_config = mkosi.config

    def _replace(self, owner, name, value):
        namespace = vars(owner)
        if name in namespace:
            self.addCleanup(setattr, owner, name, namespace[name])
        else:
            self.addCleanup(delattr, owner, name)
        setattr(owner, name, value)

    def _pinned(self):
        return self.contract.CONTRACTS[self.contract.mkosi_version()]

    def test_pinned_mkosi_matches_its_contract(self):
        self.assertEqual([], self.contract.violations())
        self.contract.verify()

    def test_every_supported_mkosi_version_has_a_contract(self):
        versions = set(re.findall(r'^\s*"([^"]+)": struct\(', VERSIONS_BZL.read_text(), re.MULTILINE))
        self.assertTrue(versions)
        self.assertEqual(versions, set(self.contract.CONTRACTS), "add a release mode contract for each mkosi version")
        self.assertIn(self.contract.mkosi_version(), versions)

    def test_unsupported_mkosi_version_is_rejected(self):
        self.assertEqual(
            ["mkosi 0 is not supported by release mode; supported mkosi versions: 27"],
            self.contract.violations(version="0"),
        )

    def test_changed_internal_fails_loudly_with_the_patch_to_review(self):
        def parse_ini(path, only_sections=()):
            yield from ()

        self._replace(self.mkosi_config, "parse_ini", parse_ini)
        with self.assertRaises(SystemExit) as raised:
            self.contract.verify()
        message = str(raised.exception)
        self.assertIn("internals that rules_mkosi release mode patches differ", message)
        self.assertIn("mkosi.config:parse_ini changed; _ConfigurationValidator.parse_ini replaces or wraps it", message)
        self.assertIn("release_patches.py", message)
        self.assertIn("mkosi_contract.py", message)

    def test_removed_internal_is_reported(self):
        contract = dataclasses.replace(
            self._pinned(), patched=(self.contract.Patched("mkosi.config:no_such_function", "_patch", "0"),)
        )
        self.assertEqual(
            ["mkosi.config:no_such_function no longer exists; _patch cannot patch it"],
            self.contract.violations(contract=contract),
        )

    def test_caller_that_no_longer_reads_the_patched_name_is_reported(self):
        parse_ini = next(patched for patched in self._pinned().patched if patched.name == "mkosi.config:parse_ini")
        moved = dataclasses.replace(parse_ini, callers=("mkosi.config:parse_boolean",))
        contract = dataclasses.replace(self._pinned(), patched=(moved,))
        self.assertEqual(
            [
                "mkosi.config:parse_boolean no longer reads parse_ini from its module; "
                "_ConfigurationValidator.parse_ini would not take effect"
            ],
            self.contract.violations(contract=contract),
        )

    def test_callers_that_bypass_the_patched_module_global_are_reported(self):
        # Only a module-global read sees the patched mkosi.make_tar; an attribute read or a function-local import
        # binds the original function and silently bypasses the patch.
        module = types.ModuleType("rules_mkosi_contract_callers")
        exec(_CALLERS, module.__dict__)
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__)
        make_tar = next(patched for patched in self._pinned().patched if patched.name == "mkosi:make_tar")

        def caller_violations(caller):
            patched = dataclasses.replace(make_tar, callers=("rules_mkosi_contract_callers:" + caller,))
            return self.contract.violations(contract=dataclasses.replace(self._pinned(), patched=(patched,)))

        for caller in ("global_caller", "nested_global_caller"):
            with self.subTest(caller=caller):
                self.assertEqual([], caller_violations(caller))
        for caller in ("attribute_caller", "local_import_caller"):
            with self.subTest(caller=caller):
                self.assertEqual(
                    [
                        "rules_mkosi_contract_callers:{} no longer reads make_tar from its module; "
                        "deterministic_make_tar would not take effect".format(caller)
                    ],
                    caller_violations(caller),
                )

    def test_subclass_override_of_a_patched_method_is_reported(self):
        import mkosi.installer.apt

        self._replace(mkosi.installer.apt.Apt, "mounts", classmethod(lambda cls, context: []))
        self.assertIn(
            "mkosi.installer.apt:Apt now overrides mounts, which release mode patches in its base class",
            self.contract.violations(),
        )

    def test_changed_helper_parameters_and_missing_fields_are_reported(self):
        contract = dataclasses.replace(
            self._pinned(),
            patched=(),
            signatures={"mkosi.run:workdir": "path"},
            fields={"mkosi.config:Config": ("image", "no_such_field")},
        )
        self.assertEqual(
            [
                "mkosi.run:workdir parameters changed from (path) to (path, sandbox=); release mode calls it",
                "mkosi.config:Config has no field no_such_field; release mode reads it",
            ],
            self.contract.violations(contract=contract),
        )

    def test_release_mode_verifies_mkosi_before_patching(self):
        self._replace(self.contract, "CONTRACTS", {})
        original = self.mkosi_config.parse_config
        settings = self.release_validation.ReleaseSettings(
            seed="00000000-0000-4000-8000-000000000015",
            source_date_epoch=0,
            distribution="debian",
            codename="trixie",
            snapshot="20250814T000000Z",
            stage="finalize",
        )
        with self.assertRaisesRegex(SystemExit, "mkosi 27 is not supported by release mode"):
            self.release_patches.activate_release_mode(None, settings, [], None)
        self.assertIs(original, self.mkosi_config.parse_config)

    def test_local_mirror_repository_is_the_one_that_release_mode_rewrites(self):
        from mkosi.distribution.debian import Installer

        config = types.SimpleNamespace(
            repositories=["contrib"], mirror=None, snapshot=None, local_mirror="file:///mirror", release="trixie"
        )
        repositories = list(Installer.repositories(types.SimpleNamespace(config=config)))
        self.assertEqual(["file:///mirror"], [repository.url for repository in repositories])
        # mkosi registers only main for a local mirror, which is why release mode lists the snapshot components.
        self.assertEqual(("main",), repositories[0].components)

    def test_context_creates_the_repository_directory_that_release_mode_replaces(self):
        from mkosi.context import Context

        with tempfile.TemporaryDirectory() as directory:
            workspace = pathlib.Path(directory)
            context = Context(
                None, None, workspace=workspace, resources=workspace, keyring_dir=workspace, metadata_dir=workspace
            )
            self.assertEqual(workspace / "repository", context.repository)
            self.assertTrue((workspace / "repository").is_dir())

    def test_parse_ini_reports_the_sections_that_release_mode_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "mkosi.conf"
            path.write_text("[Match]\nDistribution=debian\n[Content]\nBootable=yes\n")
            entries = list(self.mkosi_config.parse_ini(path))
            self.assertEqual(["Match", "Content"], list(dict.fromkeys(section for section, _, _ in entries)))
            self.assertIn(("Match", "Distribution", "debian"), entries)

    def test_release_validation_reads_only_existing_config_fields(self):
        fields = {field.name for field in dataclasses.fields(self.mkosi_config.Config)}
        source = pathlib.Path(self.release_validation.__file__).read_text()
        names = {
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.fullmatch(r"[a-z][a-z0-9_]*", node.value)
        }
        # A renamed mkosi field would otherwise make a getattr() default silently skip its check.
        self.assertEqual(set(), names - fields - _VALIDATION_WORDS, "release_validation.py reads unknown Config fields")
        self.assertIn("microcode_host", names & fields)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
