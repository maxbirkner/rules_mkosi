"""Regression tests for the wrapper's input-root and metadata handling."""

import importlib.util
import inspect
import json
import os
import pathlib
import shutil
import stat
import sys
import types
import unittest
import uuid

SEED = "00000000-0000-4000-8000-000000000015"
SNAPSHOT = "20250814T000000Z"


def _load_wrapper(path):
    spec = importlib.util.spec_from_file_location("run_mkosi", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare(root, name, mode, timestamp):
    source = root / name
    (source / "linked-dir").mkdir(parents=True)
    (source / "file-target").write_text("file\n")
    (source / "linked-dir" / "marker").write_text("directory\n")
    (source / "linked-file").symlink_to("file-target")
    (source / "linked-directory").symlink_to("linked-dir")
    os.chmod(source / "file-target", mode)
    os.chmod(source / "linked-dir" / "marker", mode)
    os.utime(source / "file-target", (timestamp, timestamp))
    os.utime(source / "linked-dir" / "marker", (timestamp, timestamp))
    os.symlink(source, root / "{}-root-link".format(name))
    return source


def _assert_normalized(path):
    assert stat.S_IMODE(path.stat().st_mode) == 0o755
    assert path.stat().st_mtime == 0
    assert stat.S_IMODE((path / "file-target").stat().st_mode) == 0o644
    assert (path / "file-target").stat().st_mtime == 0
    assert stat.S_IMODE((path / "linked-dir").stat().st_mode) == 0o755
    assert (path / "linked-dir").stat().st_mtime == 0
    assert (path / "linked-file").is_symlink()
    assert os.readlink(path / "linked-file") == "file-target"
    assert (path / "linked-directory").is_symlink()
    assert os.readlink(path / "linked-directory") == "linked-dir"


def _expect_exit(function, message):
    try:
        function()
    except SystemExit as error:
        assert message in str(error), error
    else:
        raise AssertionError("expected failure containing {!r}".format(message))


def _configuration(**settings):
    values = {"seed": uuid.UUID(SEED), "source_date_epoch": 0}
    values.update(settings)
    return types.SimpleNamespace(**values)


def _validate(wrapper, configuration, allowed_paths, allowed_extra_tree=None, **settings):
    validation = wrapper.release_validation
    release = validation.ReleaseSettings(
        seed=SEED,
        source_date_epoch=0,
        distribution="debian",
        codename="trixie",
        snapshot=SNAPSHOT,
        **settings,
    )
    return validation.validate_release_configuration([configuration], release, allowed_paths, allowed_extra_tree)


# run_mkosi.py, from the test's first argument.
_WRAPPER_PATH = None


def _base_artifacts(root):
    base_tree = root / "base/root.tar"
    base_initrd = root / "base/initrd"
    other = root / "other.tar"
    staged = root / "staged"
    if not staged.exists():
        base_tree.parent.mkdir()
        base_tree.write_bytes(b"tar")
        base_initrd.write_bytes(b"initrd")
        other.write_bytes(b"tar")
        staged.mkdir()
    return base_tree, base_initrd, other, staged


class _WrapperTest(unittest.TestCase):
    """Loads run_mkosi.py once and gives every test case its own empty directory."""

    @classmethod
    def setUpClass(cls):
        cls.wrapper = _load_wrapper(_WRAPPER_PATH)

    def setUp(self):
        self.root = pathlib.Path(os.environ["TEST_TMPDIR"]) / self._testMethodName
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)


class MaterializationTest(_WrapperTest):
    def test_materialized_metadata_does_not_depend_on_source_metadata(self):
        wrapper, root = self.wrapper, self.root
        first = _prepare(root, "first", 0o600, 946684800)
        second = _prepare(root, "second", 0o644, 1893456000)
        wrapper.tree.materialize_tree(root / "first-root-link", root / "out-first")
        wrapper.tree.materialize_tree(root / "second-root-link", root / "out-second")
        _assert_normalized(root / "out-first")
        _assert_normalized(root / "out-second")
        assert (root / "out-first/file-target").read_bytes() == (root / "out-second/file-target").read_bytes()
        assert first != second

    def test_declared_executables_keep_the_executable_mode(self):
        wrapper, root = self.wrapper, self.root
        executable = self._executable_tree()
        wrapper.tree.materialize_tree(executable, root / "out-executable", ["bin/tool"])
        assert stat.S_IMODE((root / "out-executable/bin/tool").stat().st_mode) == 0o755
        assert stat.S_IMODE((root / "out-executable/data").stat().st_mode) == 0o644

    def test_symlink_destination_is_rejected(self):
        wrapper, root = self.wrapper, self.root
        executable = self._executable_tree()
        (root / "out-first").mkdir()
        (root / "out-executable-link").symlink_to(root / "out-first")
        _expect_exit(
            lambda: wrapper.tree.materialize_tree(executable, root / "out-executable-link"),
            "materialization destination is a symlink",
        )

    def _executable_tree(self):
        executable = self.root / "executable"
        (executable / "bin").mkdir(parents=True)
        (executable / "bin/tool").write_text("#!/bin/sh\n")
        (executable / "data").write_text("data\n")
        return executable


class ManifestLinksTest(_WrapperTest):
    def setUp(self):
        super().setUp()
        self.restored = self.root / "restored"
        self.restored.mkdir()
        (self.restored / "target").write_text("target\n")
        (self.restored / "link").write_text("materialized link\n")
        self.manifest = self.root / "manifest.json"

    def test_manifest_symlinks_are_restored_with_epoch_mtimes(self):
        wrapper, restored, manifest = self.wrapper, self.restored, self.manifest
        manifest.write_text(json.dumps([{"kind": "symlink", "link_target": "target", "path": "link"}]))
        wrapper.tree.restore_manifest_links(restored, manifest)
        assert (restored / "link").is_symlink()
        assert (restored / "link").lstat().st_mtime == 0
        assert restored.stat().st_mtime == 0

    def test_invalid_manifest_links_are_rejected(self):
        wrapper, restored, manifest = self.wrapper, self.restored, self.manifest
        for entry, message in (
            ({"kind": "symlink", "link_target": "target", "path": "../escape"}, "invalid staging manifest path"),
            ({"kind": "symlink", "link_target": "target", "path": "absent"}, "staging manifest entry is missing"),
            ({"kind": "symlink", "link_target": "/target", "path": "target"}, "invalid staging manifest link"),
        ):
            with self.subTest(message=message):
                manifest.write_text(json.dumps([entry]))
                _expect_exit(lambda: wrapper.tree.restore_manifest_links(restored, manifest), message)


class ReleaseSandboxTest(_WrapperTest):
    def test_release_mirror_and_sandbox_tree_are_configured(self):
        wrapper, root = self.wrapper, self.root
        sandbox = wrapper.release_sandbox
        repository = root / "repository"
        (repository / "dists/trixie/main").mkdir(parents=True)
        (repository / "dists/trixie/main/Release").write_text("locked metadata\n")
        arguments = []
        mirror = sandbox.configure_release_mirror(repository, root / "workspace", arguments)
        assert arguments == [
            "--local-mirror",
            "file://" + os.fspath(mirror),
            "--sandbox-tree",
            os.fspath(root / "workspace/release-sandbox"),
        ]
        assert (mirror / "dists/trixie/main/Release").read_text() == "locked metadata\n"
        assert mirror.stat().st_mtime == 0
        etc = root / "workspace/release-sandbox/etc"
        assert (etc / "apt/apt.conf.d/99rules-mkosi-release").read_text() == (
            'Acquire::Languages "none";\nAcquire::By-Hash "no";\n'
        )
        assert (etc / "passwd").read_text() == sandbox.PASSWD
        assert (etc / "group").read_text() == sandbox.GROUP
        assert (etc / "hosts").read_text() == sandbox.HOSTS
        assert (etc / "nsswitch.conf").read_text() == sandbox.NSSWITCH

    def test_release_patches_do_not_read_host_identity_files(self):
        release_setup = inspect.getsource(self.wrapper.release_patches)
        for host_file in ("/etc/passwd", "/etc/group", "/etc/hosts"):
            assert host_file not in release_setup

    def test_host_dependent_matching_sections_are_rejected(self):
        wrapper = self.wrapper
        for section in ("Match", "TriggerMatch"):
            with self.subTest(section=section):
                _expect_exit(
                    lambda: wrapper.release_validation.validate_ini_section(section), "host-dependent matching"
                )
        wrapper.release_validation.validate_ini_section("Content")


class CommandLineTest(_WrapperTest):
    def test_preamble_options_are_parsed(self):
        command_line = self.wrapper.command_line
        preamble, arguments = command_line.parse_preamble(
            [
                "--executable-path",
                "bin/a",
                "--executable-path",
                "bin/b",
                "--kernel-preflight",
                "preflight",
                "--debian-tools-sha256",
                "digest",
                "--release-source-date-epoch",
                "7",
                "--release-components",
                "main,contrib",
                "--",
                "-C",
                "config",
            ]
        )
        assert preamble.executable_paths == ["bin/a", "bin/b"]
        assert preamble.kernel_preflight == os.path.abspath("preflight")
        assert preamble.debian_tools_sha256 == "digest"
        assert preamble.release_source_date_epoch == 7
        assert preamble.release_components == ("main", "contrib")
        assert preamble.release_seed is None
        assert arguments == ["-C", "config"]

    def test_invalid_preambles_are_rejected(self):
        command_line = self.wrapper.command_line
        for argv, message in (
            (["--unknown", "value", "--"], "invalid run_mkosi.py preamble"),
            (["--kernel-preflight"], "invalid run_mkosi.py preamble"),
            (["--kernel-preflight", "preflight"], "run_mkosi.py preamble is missing --"),
            (["--release-seed", "seed", "--"], "run_mkosi.py requires --kernel-preflight"),
            (["--release-source-date-epoch", "now", "--"], "release source date epoch must be an integer"),
            (["--release-components", "contrib", "--"], "comma-separated list including main"),
            (["--release-components", "main,", "--"], "comma-separated list including main"),
        ):
            with self.subTest(argv=argv):
                _expect_exit(lambda argv=argv: command_line.parse_preamble(argv), message)

    def test_mkosi_path_options_are_made_absolute(self):
        command_line = self.wrapper.command_line
        assert command_line.absolute_paths(["--include=config", "--format=disk", "build"]) == [
            "--include=" + os.path.abspath("config"),
            "--format=disk",
            "build",
        ]
        _expect_exit(lambda: command_line.absolute_paths(["--tools-tree"]), "mkosi path option is missing its value")

    def test_declared_paths_skip_mkosi_constants(self):
        command_line = self.wrapper.command_line
        assert command_line.declared_paths(
            ["-C", "/config", "--initrd", "default", "--initrd", "/initrd", "--base-tree=/base"]
        ) == ["/config", "/initrd", "/base"]

    def test_initrd_default_constant_is_not_made_absolute(self):
        command_line = self.wrapper.command_line
        # mkosi's "default" initrd constant is not a path relative to the action's working directory.
        assert command_line.absolute_paths(
            ["--initrd=default", "--initrd", "default", "--base-tree", "base.tar"]
        ) == [
            "--initrd=default",
            "--initrd",
            "default",
            "--base-tree",
            os.path.abspath("base.tar"),
        ]
        assert command_line.absolute_paths(["--initrd", "initrd"]) == ["--initrd", os.path.abspath("initrd")]

    def test_mkosi_option_value_comes_from_exactly_one_mkosi_argument(self):
        command_line = self.wrapper.command_line
        argv = ["--release-seed", "x", "--", "--output-directory", "out"]
        assert command_line.mkosi_option_value(argv, "--output-directory") == "out"
        _expect_exit(
            lambda: command_line.mkosi_option_value(["--output-directory", "preamble", "--"], "--output-directory"),
            "expected exactly one mkosi --output-directory argument",
        )

    def test_release_stage_follows_the_release_inputs(self):
        command_line = self.wrapper.command_line
        assert command_line.release_stage(False, None, None, None, None) is None
        assert command_line.release_stage(True, "repository", None, None, None) == "image"
        assert command_line.release_stage(True, "repository", None, None, "initrd") == "base"
        assert command_line.release_stage(True, None, "root.tar", "initrd", None) == "finalize"

    def test_inconsistent_release_inputs_are_rejected(self):
        command_line = self.wrapper.command_line
        for options, message in (
            ((True, None, "root.tar", None, None), "requires both --release-base-tree and --release-initrd"),
            ((True, "repository", "root.tar", "initrd", None), "cannot use the Debian snapshot or produce a base"),
            ((True, None, "root.tar", "initrd", "initrd"), "cannot use the Debian snapshot or produce a base"),
            ((True, None, None, None, "initrd"), "a release base requires the Debian snapshot repository"),
            ((False, "repository", None, None, None), "incomplete release configuration"),
            ((False, None, "root.tar", "initrd", None), "incomplete release configuration"),
            ((True, None, None, None, None), "incomplete release configuration"),
        ):
            with self.subTest(options=options):
                _expect_exit(lambda options=options: command_line.release_stage(*options), message)


class ReleaseConfigurationTest(_WrapperTest):
    def test_reproducible_release_configuration_is_accepted(self):
        _validate(self.wrapper, _configuration(), [self.root])

    def test_apt_components_are_main_plus_the_requested_snapshot_components(self):
        snapshot_components = ("main", "non-free-firmware")
        assert self.wrapper.release_validation.release_apt_components([], snapshot_components) == ("main",)
        assert (
            self.wrapper.release_validation.release_apt_components(
                ["non-free-firmware", "main", "non-free-firmware"],
                snapshot_components,
            )
            == snapshot_components
        )

    def test_repositories_must_be_snapshot_components(self):
        wrapper, root = self.wrapper, self.root
        snapshot_components = ("main", "non-free-firmware")
        _validate(wrapper, _configuration(repositories=["non-free-firmware"]), [root], components=snapshot_components)
        for repositories, components in (
            (["non-free-firmware"], ("main",)),
            (["contrib"], snapshot_components),
        ):
            with self.subTest(repositories=repositories, components=components):
                _expect_exit(
                    lambda: _validate(
                        wrapper, _configuration(repositories=repositories), [root], components=components
                    ),
                    "absent from the Debian snapshot: " + repositories[0],
                )

    def test_declared_extra_tree_is_accepted(self):
        wrapper, root = self.wrapper, self.root
        safe_extra = root / "mkosi.extra"
        _validate(wrapper, _configuration(extra_trees=[types.SimpleNamespace(source=safe_extra)]), [root], safe_extra)

    def test_bios_release_rejects_uefi_settings(self):
        wrapper, root = self.wrapper, self.root
        for setting, value, message in (
            ("secure_boot", True, "SecureBoot"),
            ("unified_kernel_images", types.SimpleNamespace(value="yes"), "UnifiedKernelImages"),
            ("bootloader", types.SimpleNamespace(value="systemd-boot"), "UEFI Bootloader"),
        ):
            with self.subTest(setting=setting):
                _expect_exit(
                    lambda: _validate(wrapper, _configuration(**{setting: value}), [root], firmware="bios"),
                    message,
                )

    def test_unreproducible_or_host_dependent_settings_are_rejected(self):
        wrapper, root = self.wrapper, self.root
        for configuration, message in (
            (_configuration(seed=uuid.uuid4()), "Seed"),
            (_configuration(source_date_epoch=None), "SourceDateEpoch"),
            (_configuration(skeleton_trees=[types.SimpleNamespace(source=pathlib.Path("/etc"))]), "undeclared path"),
            (
                _configuration(proxy_peer_certificate=pathlib.Path("/etc/ssl/certs/ca-certificates.crt")),
                "undeclared path",
            ),
            (_configuration(proxy_url="http://proxy"), "cannot use a proxy"),
            (_configuration(extra_trees=[types.SimpleNamespace(source=root)]), "extra_trees is not supported"),
            (_configuration(microcode_host=True), "microcode_host is not supported"),
            (_configuration(build_scripts=[root / "build.sh"]), "build_scripts is not supported"),
            (_configuration(kernel_modules_include_host=True), "kernel_modules_include_host is not supported"),
            (
                _configuration(kernel_modules_initrd_include_host=True),
                "kernel_modules_initrd_include_host is not supported",
            ),
            (_configuration(kernel_modules_include=["host"]), "kernel_modules_include cannot include host modules"),
            (
                _configuration(kernel_modules_initrd_include=["host"]),
                "kernel_modules_initrd_include cannot include host modules",
            ),
            (
                _configuration(
                    distribution=types.SimpleNamespace(value="ubuntu"),
                    release="noble",
                    snapshot=SNAPSHOT,
                ),
                "must resolve to debian trixie snapshot",
            ),
            (
                _configuration(secure_boot_key_source=types.SimpleNamespace(source="engine")),
                "secure_boot_key_source is not supported",
            ),
            (_configuration(incremental=types.SimpleNamespace(value="yes")), "incremental mode is not supported"),
        ):
            with self.subTest(message=message):
                _expect_exit(lambda: _validate(wrapper, configuration, [root]), message)


class TwoStageReleaseTest(_WrapperTest):
    def test_finalization_sandbox_tree_is_configured(self):
        wrapper, root = self.wrapper, self.root
        arguments = []
        wrapper.release_sandbox.configure_release_sandbox(root / "finalize-workspace", arguments)
        assert arguments == ["--sandbox-tree", os.fspath(root / "finalize-workspace/release-sandbox")]
        assert (root / "finalize-workspace/release-sandbox/etc/passwd").read_text() == wrapper.release_sandbox.PASSWD

    def test_release_tar_command_is_sorted_and_owned_by_root(self):
        wrapper = self.wrapper
        tar = wrapper.release_patches.tar_command("/work/root", ["--exclude=./proc"], 1000)
        assert "--sort=name" in tar and "--sparse" not in tar
        assert tar[-4:] == ["--owner=root:0", "--group=root:0", "--exclude=./proc", "."]
        assert "--owner=root:0" not in wrapper.release_patches.tar_command("/work/root", [], 0)


class BaseInitrdPublicationTest(_WrapperTest):
    def setUp(self):
        super().setUp()
        self.output_directory = self.root / "base-output"
        self.output_directory.mkdir()
        (self.output_directory / "initrd.cpio.zst").write_bytes(b"initrd")

    def test_default_initrd_is_published_and_its_link_removed(self):
        wrapper, root, output_directory = self.wrapper, self.root, self.output_directory
        (output_directory / "initrd").symlink_to("initrd.cpio.zst")
        wrapper._publish_base_initrd(output_directory, root / "base.initrd")
        assert (root / "base.initrd").read_bytes() == b"initrd"
        assert not (output_directory / "initrd").exists() and not (output_directory / "initrd").is_symlink()

    def test_missing_default_initrd_link_is_rejected(self):
        wrapper, root, output_directory = self.wrapper, self.root, self.output_directory
        _expect_exit(
            lambda: wrapper._publish_base_initrd(output_directory, root / "missing.initrd"),
            "did not produce the default initrd link",
        )

    def test_default_initrd_link_outside_the_output_directory_is_rejected(self):
        wrapper, root, output_directory = self.wrapper, self.root, self.output_directory
        outside = root / "outside.cpio"
        outside.write_bytes(b"outside")
        (output_directory / "initrd").symlink_to(outside)
        _expect_exit(
            lambda: wrapper._publish_base_initrd(output_directory, root / "outside.initrd"),
            "is not a file in the output directory",
        )


class FinalizeConfigurationTest(_WrapperTest):
    def setUp(self):
        super().setUp()
        self.base_tree, self.base_initrd, self.other, self.staged = _base_artifacts(self.root)

    def _finalize(self, **settings):
        values = {
            "distribution": types.SimpleNamespace(value="debian"),
            "release": "trixie",
            "snapshot": None,
            "base_trees": [self.base_tree],
            "initrds": [self.base_initrd],
        }
        values.update(settings)
        return _validate(
            self.wrapper,
            _configuration(**values),
            [self.staged],
            stage="finalize",
            base_tree=self.base_tree,
            base_initrd=self.base_initrd,
        )

    def test_declared_base_artifacts_are_allowed_outside_staged_paths(self):
        assert self.base_tree.resolve() in self._finalize()

    def test_finalization_accepts_cache_snapshot_and_initrd_module_settings(self):
        finalize = self._finalize
        finalize(cacheonly=types.SimpleNamespace(value="always"))
        finalize(snapshot=SNAPSHOT)
        # The finalization builds the kernel modules initrd, so it accepts these settings.
        finalize(
            kernel_modules_initrd=False,
            kernel_modules_initrd_include=["virtio"],
            kernel_modules_initrd_exclude=["drm"],
        )

    def test_finalization_rejects_package_and_base_changes(self):
        finalize, base_tree, base_initrd, other, staged = (
            self._finalize,
            self.base_tree,
            self.base_initrd,
            self.other,
            self.staged,
        )
        for settings, message in (
            ({"snapshot": "20260101T000000Z"}, "must resolve to debian trixie snapshot"),
            ({"packages": ["vim"]}, "cannot use Packages="),
            ({"build_packages": ["gcc"]}, "cannot use BuildPackages="),
            ({"volatile_packages": ["vim"]}, "cannot use VolatilePackages="),
            ({"remove_packages": ["apt"]}, "cannot use RemovePackages="),
            ({"package_directories": [staged]}, "cannot use PackageDirectories="),
            ({"volatile_package_directories": [staged]}, "cannot use VolatilePackageDirectories="),
            ({"base_trees": []}, "BaseTrees= must resolve to exactly the declared base tree"),
            ({"base_trees": [base_tree, other]}, "BaseTrees= must resolve to exactly the declared base tree"),
            ({"base_trees": [other]}, "BaseTrees= must resolve to exactly the declared base tree"),
            ({"initrds": []}, "Initrds= must resolve to exactly the declared base initrd"),
            ({"initrds": [base_initrd, other]}, "Initrds= must resolve to exactly the declared base initrd"),
            ({"cacheonly": types.SimpleNamespace(value="auto")}, "CacheOnly= must resolve to always"),
            (
                {"initrd_packages": ["cryptsetup"]},
                "cannot use InitrdPackages=: the default initrd is built by mkosi_base",
            ),
            ({"initrd_volatile_packages": ["vim"]}, "cannot use InitrdVolatilePackages="),
            ({"initrd_profiles": ["lvm"]}, "cannot use InitrdProfiles="),
            ({"skeleton_trees": [types.SimpleNamespace(source=pathlib.Path("/etc"))]}, "undeclared path"),
        ):
            with self.subTest(settings=settings):
                _expect_exit(lambda settings=settings: finalize(**settings), message)

    def test_finalization_requires_declared_base_artifacts(self):
        _expect_exit(
            lambda: _validate(self.wrapper, _configuration(), [self.staged], stage="finalize"),
            "requires a declared base tree and initrd",
        )

    def test_unknown_release_stage_is_rejected(self):
        _expect_exit(
            lambda: _validate(self.wrapper, _configuration(), [self.staged], stage="incremental"),
            "unknown release stage incremental",
        )


class BaseConfigurationTest(_WrapperTest):
    def setUp(self):
        super().setUp()
        _, _, self.other, self.staged = _base_artifacts(self.root)

    def _base(self, **settings):
        return _validate(self.wrapper, _configuration(**settings), [self.staged], stage="base")

    def test_base_accepts_initrd_and_image_id_settings(self):
        base = self._base
        base()
        base(image_id="rules-mkosi-ab")
        base(kernel_modules_initrd=True, initrd_packages=["cryptsetup"], initrd_profiles=["lvm"])

    def test_base_rejects_finalization_settings(self):
        base, other = self._base, self.other
        for settings, message in (
            ({"kernel_modules_initrd": False}, "cannot use KernelModulesInitrd=no"),
            (
                {"kernel_modules_initrd_include": ["virtio"]},
                "cannot use KernelModulesInitrdInclude=/KernelInitrdModules=",
            ),
            ({"kernel_modules_initrd_exclude": ["drm"]}, "cannot use KernelModulesInitrdExclude="),
            ({"image_version": "1"}, "release base configuration cannot set ImageVersion="),
            ({"base_trees": [other]}, "release configuration base_trees resolves undeclared path"),
        ):
            with self.subTest(settings=settings):
                _expect_exit(lambda settings=settings: base(**settings), message)


class FinalizeConfigDirectoryTest(_WrapperTest):
    def setUp(self):
        super().setUp()
        self.validate = self.wrapper.release_validation.validate_finalize_config_directory

    def test_configuration_without_initrd_settings_is_accepted(self):
        finalize_config = self.root / "finalize-config"
        finalize_config.mkdir()
        (finalize_config / "mkosi.conf").write_text("[Content]\nBootable=yes\n")
        self.validate(finalize_config)

    def test_initrd_configuration_is_rejected(self):
        validate = self.validate
        finalize_config = self.root / "finalize-config"
        finalize_config.mkdir()
        (finalize_config / "mkosi.conf").write_text("[Content]\nBootable=yes\n")
        for name, is_directory in (("mkosi.initrd.conf", False), ("mkosi.initrd.conf", True), ("mkosi.initrd", True)):
            with self.subTest(name=name, is_directory=is_directory):
                path = finalize_config / name
                if is_directory:
                    path.mkdir()
                else:
                    path.write_text("[Content]\nPackages=cryptsetup\n")
                _expect_exit(
                    lambda: validate(finalize_config),
                    "cannot contain {}: the default initrd is built by mkosi_base".format(name),
                )
                if is_directory:
                    path.rmdir()
                else:
                    path.unlink()

    def test_nested_initrd_configuration_is_rejected(self):
        validate = self.validate
        nested = self.root / "nested-finalize-config"
        (nested / "mkosi").mkdir(parents=True)
        (nested / "mkosi/mkosi.conf").write_text("[Content]\nBootable=yes\n")
        (nested / "mkosi/mkosi.initrd.conf").write_text("[Content]\nPackages=cryptsetup\n")
        _expect_exit(lambda: validate(nested), "cannot contain mkosi.initrd.conf")


class StagedConfigurationTest(_WrapperTest):
    def setUp(self):
        super().setUp()
        self.preamble = self.wrapper.command_line.Preamble()

    def _stage(self):
        """Stages a -C configuration with an initrd file; returns the staged directory and the rewritten arguments."""
        configuration = self.root / "staged-finalize"
        configuration.mkdir()
        (configuration / "mkosi.conf").write_text("[Content]\nBootable=yes\n")
        (configuration / "mkosi.initrd.conf").write_text("[Content]\nPackages=cryptsetup\n")
        workspace = self.root / "staged-finalize-workspace"
        arguments = ["-C", os.fspath(configuration), "-I", os.fspath(configuration / "mkosi.conf")]
        arguments += ["--workspace-directory", os.fspath(workspace)]
        return self.wrapper._stage_configuration(self.preamble, arguments), arguments, workspace

    def test_configuration_is_staged_into_the_workspace(self):
        staged, arguments, workspace = self._stage()
        assert staged == workspace / "staging-root"
        assert arguments == [
            "-C",
            os.fspath(staged),
            "-I",
            os.fspath(staged / "mkosi.conf"),
            "--workspace-directory",
            os.fspath(workspace),
        ]
        assert (staged / "mkosi.conf").read_text() == "[Content]\nBootable=yes\n"

    def test_finalization_rejects_the_staged_initrd_configuration(self):
        wrapper, preamble = self.wrapper, self.preamble
        staged, arguments, _ = self._stage()
        # The finalization rejects the staged copy before it patches mkosi.
        _expect_exit(
            lambda: wrapper._activate_release_mode(preamble, arguments, "finalize", None, staged),
            "cannot contain mkosi.initrd.conf",
        )

    def test_image_stage_requires_a_staged_configuration_directory(self):
        wrapper, preamble = self.wrapper, self.preamble
        _expect_exit(
            lambda: wrapper._activate_release_mode(preamble, [], "image", None, None),
            "requires a staged -C configuration directory",
        )

    def test_arguments_without_a_configuration_directory_are_not_staged(self):
        assert self.wrapper._stage_configuration(self.preamble, ["build"]) is None


if __name__ == "__main__":
    _WRAPPER_PATH = sys.argv.pop(1)
    # run_mkosi.py reads mkosi's option table, so mkosi must be importable like in the image action.
    sys.path.insert(0, os.fspath(pathlib.Path(sys.argv.pop(1)).resolve().parents[1]))
    unittest.main()
