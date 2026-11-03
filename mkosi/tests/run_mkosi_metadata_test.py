"""Regression tests for the wrapper's input-root and metadata handling."""

import importlib.util
import inspect
import json
import os
import pathlib
import stat
import sys
import types
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


def main():
    # run_mkosi.py reads mkosi's option table, so mkosi must be importable like in the image action.
    sys.path.insert(0, os.fspath(pathlib.Path(sys.argv[2]).resolve().parents[1]))
    wrapper = _load_wrapper(sys.argv[1])
    root = pathlib.Path(os.environ["TEST_TMPDIR"])
    _check_materialization(wrapper, root)
    _check_manifest_links(wrapper, root)
    _check_release_sandbox(wrapper, root)
    _check_preamble(wrapper)
    _check_release_configuration(wrapper, root)
    _check_two_stage_release(wrapper, root)
    print("materialized metadata and relative links are deterministic")


def _check_materialization(wrapper, root):
    first = _prepare(root, "first", 0o600, 946684800)
    second = _prepare(root, "second", 0o644, 1893456000)
    wrapper.tree.materialize_tree(root / "first-root-link", root / "out-first")
    wrapper.tree.materialize_tree(root / "second-root-link", root / "out-second")
    _assert_normalized(root / "out-first")
    _assert_normalized(root / "out-second")
    assert (root / "out-first/file-target").read_bytes() == (root / "out-second/file-target").read_bytes()
    assert first != second

    executable = root / "executable"
    (executable / "bin").mkdir(parents=True)
    (executable / "bin/tool").write_text("#!/bin/sh\n")
    (executable / "data").write_text("data\n")
    wrapper.tree.materialize_tree(executable, root / "out-executable", ["bin/tool"])
    assert stat.S_IMODE((root / "out-executable/bin/tool").stat().st_mode) == 0o755
    assert stat.S_IMODE((root / "out-executable/data").stat().st_mode) == 0o644
    (root / "out-executable-link").symlink_to(root / "out-first")
    _expect_exit(
        lambda: wrapper.tree.materialize_tree(executable, root / "out-executable-link"),
        "materialization destination is a symlink",
    )


def _check_manifest_links(wrapper, root):
    restored = root / "restored"
    restored.mkdir()
    (restored / "target").write_text("target\n")
    (restored / "link").write_text("materialized link\n")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps([{"kind": "symlink", "link_target": "target", "path": "link"}]))
    wrapper.tree.restore_manifest_links(restored, manifest)
    assert (restored / "link").is_symlink()
    assert (restored / "link").lstat().st_mtime == 0
    assert restored.stat().st_mtime == 0
    for entry, message in (
        ({"kind": "symlink", "link_target": "target", "path": "../escape"}, "invalid staging manifest path"),
        ({"kind": "symlink", "link_target": "target", "path": "absent"}, "staging manifest entry is missing"),
        ({"kind": "symlink", "link_target": "/target", "path": "target"}, "invalid staging manifest link"),
    ):
        manifest.write_text(json.dumps([entry]))
        _expect_exit(lambda: wrapper.tree.restore_manifest_links(restored, manifest), message)


def _check_release_sandbox(wrapper, root):
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
    release_setup = inspect.getsource(wrapper.release_patches)
    for host_file in ("/etc/passwd", "/etc/group", "/etc/hosts"):
        assert host_file not in release_setup
    for section in ("Match", "TriggerMatch"):
        _expect_exit(lambda: wrapper.release_validation.validate_ini_section(section), "host-dependent matching")
    wrapper.release_validation.validate_ini_section("Content")


def _check_preamble(wrapper):
    command_line = wrapper.command_line
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
    for argv, message in (
        (["--unknown", "value", "--"], "invalid run_mkosi.py preamble"),
        (["--kernel-preflight"], "invalid run_mkosi.py preamble"),
        (["--kernel-preflight", "preflight"], "run_mkosi.py preamble is missing --"),
        (["--release-seed", "seed", "--"], "run_mkosi.py requires --kernel-preflight"),
        (["--release-source-date-epoch", "now", "--"], "release source date epoch must be an integer"),
        (["--release-components", "contrib", "--"], "comma-separated list including main"),
        (["--release-components", "main,", "--"], "comma-separated list including main"),
    ):
        _expect_exit(lambda argv=argv: command_line.parse_preamble(argv), message)

    assert command_line.absolute_paths(["--include=config", "--format=disk", "build"]) == [
        "--include=" + os.path.abspath("config"),
        "--format=disk",
        "build",
    ]
    _expect_exit(lambda: command_line.absolute_paths(["--tools-tree"]), "mkosi path option is missing its value")


def _check_release_configuration(wrapper, root):
    _validate(wrapper, _configuration(), [root])
    snapshot_components = ("main", "non-free-firmware")
    assert wrapper.release_validation.release_apt_components([], snapshot_components) == ("main",)
    assert (
        wrapper.release_validation.release_apt_components(
            ["non-free-firmware", "main", "non-free-firmware"],
            snapshot_components,
        )
        == snapshot_components
    )
    _validate(wrapper, _configuration(repositories=["non-free-firmware"]), [root], components=snapshot_components)
    for repositories, components in (
        (["non-free-firmware"], ("main",)),
        (["contrib"], snapshot_components),
    ):
        _expect_exit(
            lambda: _validate(wrapper, _configuration(repositories=repositories), [root], components=components),
            "absent from the Debian snapshot: " + repositories[0],
        )
    safe_extra = root / "mkosi.extra"
    _validate(wrapper, _configuration(extra_trees=[types.SimpleNamespace(source=safe_extra)]), [root], safe_extra)
    for setting, value, message in (
        ("secure_boot", True, "SecureBoot"),
        ("unified_kernel_images", types.SimpleNamespace(value="yes"), "UnifiedKernelImages"),
        ("bootloader", types.SimpleNamespace(value="systemd-boot"), "UEFI Bootloader"),
    ):
        _expect_exit(
            lambda: _validate(wrapper, _configuration(**{setting: value}), [root], firmware="bios"),
            message,
        )
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
        _expect_exit(lambda: _validate(wrapper, configuration, [root]), message)


def _check_two_stage_release(wrapper, root):
    _check_two_stage_arguments(wrapper, root)
    _check_base_initrd_publication(wrapper, root)
    _check_finalize_configuration(wrapper, root)
    _check_base_configuration(wrapper, root)
    _check_finalize_config_directory(wrapper, root)
    _check_staged_configuration(wrapper, root)
    tar = wrapper.release_patches.tar_command("/work/root", ["--exclude=./proc"], 1000)
    assert "--sort=name" in tar and "--sparse" not in tar
    assert tar[-4:] == ["--owner=root:0", "--group=root:0", "--exclude=./proc", "."]
    assert "--owner=root:0" not in wrapper.release_patches.tar_command("/work/root", [], 0)


def _check_two_stage_arguments(wrapper, root):
    command_line = wrapper.command_line
    arguments = []
    wrapper.release_sandbox.configure_release_sandbox(root / "finalize-workspace", arguments)
    assert arguments == ["--sandbox-tree", os.fspath(root / "finalize-workspace/release-sandbox")]
    assert (root / "finalize-workspace/release-sandbox/etc/passwd").read_text() == wrapper.release_sandbox.PASSWD

    # mkosi's "default" initrd constant is not a path relative to the action's working directory.
    assert command_line.absolute_paths(["--initrd=default", "--initrd", "default", "--base-tree", "base.tar"]) == [
        "--initrd=default",
        "--initrd",
        "default",
        "--base-tree",
        os.path.abspath("base.tar"),
    ]
    assert command_line.absolute_paths(["--initrd", "initrd"]) == ["--initrd", os.path.abspath("initrd")]
    argv = ["--release-seed", "x", "--", "--output-directory", "out"]
    assert command_line.mkosi_option_value(argv, "--output-directory") == "out"
    _expect_exit(
        lambda: command_line.mkosi_option_value(["--output-directory", "preamble", "--"], "--output-directory"),
        "expected exactly one mkosi --output-directory argument",
    )

    assert command_line.release_stage(False, None, None, None, None) is None
    assert command_line.release_stage(True, "repository", None, None, None) == "image"
    assert command_line.release_stage(True, "repository", None, None, "initrd") == "base"
    assert command_line.release_stage(True, None, "root.tar", "initrd", None) == "finalize"
    for options, message in (
        ((True, None, "root.tar", None, None), "requires both --release-base-tree and --release-initrd"),
        ((True, "repository", "root.tar", "initrd", None), "cannot use the Debian snapshot or produce a base"),
        ((True, None, "root.tar", "initrd", "initrd"), "cannot use the Debian snapshot or produce a base"),
        ((True, None, None, None, "initrd"), "a release base requires the Debian snapshot repository"),
        ((False, "repository", None, None, None), "incomplete release configuration"),
        ((False, None, "root.tar", "initrd", None), "incomplete release configuration"),
        ((True, None, None, None, None), "incomplete release configuration"),
    ):
        _expect_exit(lambda options=options: command_line.release_stage(*options), message)


def _check_base_initrd_publication(wrapper, root):
    output_directory = root / "base-output"
    output_directory.mkdir()
    (output_directory / "initrd.cpio.zst").write_bytes(b"initrd")
    (output_directory / "initrd").symlink_to("initrd.cpio.zst")
    wrapper._publish_base_initrd(output_directory, root / "base.initrd")
    assert (root / "base.initrd").read_bytes() == b"initrd"
    assert not (output_directory / "initrd").exists() and not (output_directory / "initrd").is_symlink()
    _expect_exit(
        lambda: wrapper._publish_base_initrd(output_directory, root / "missing.initrd"),
        "did not produce the default initrd link",
    )
    outside = root / "outside.cpio"
    outside.write_bytes(b"outside")
    (output_directory / "initrd").symlink_to(outside)
    _expect_exit(
        lambda: wrapper._publish_base_initrd(output_directory, root / "outside.initrd"),
        "is not a file in the output directory",
    )


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


def _check_finalize_configuration(wrapper, root):
    base_tree, base_initrd, other, staged = _base_artifacts(root)

    def finalize(**settings):
        values = {
            "distribution": types.SimpleNamespace(value="debian"),
            "release": "trixie",
            "snapshot": None,
            "base_trees": [base_tree],
            "initrds": [base_initrd],
        }
        values.update(settings)
        return _validate(
            wrapper,
            _configuration(**values),
            [staged],
            stage="finalize",
            base_tree=base_tree,
            base_initrd=base_initrd,
        )

    # The declared base artifacts are allowed although they are outside every staged path option.
    assert base_tree.resolve() in finalize()
    finalize(cacheonly=types.SimpleNamespace(value="always"))
    finalize(snapshot=SNAPSHOT)
    # The finalization builds the kernel modules initrd, so it accepts these settings.
    finalize(
        kernel_modules_initrd=False,
        kernel_modules_initrd_include=["virtio"],
        kernel_modules_initrd_exclude=["drm"],
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
        ({"initrd_packages": ["cryptsetup"]}, "cannot use InitrdPackages=: the default initrd is built by mkosi_base"),
        ({"initrd_volatile_packages": ["vim"]}, "cannot use InitrdVolatilePackages="),
        ({"initrd_profiles": ["lvm"]}, "cannot use InitrdProfiles="),
        ({"skeleton_trees": [types.SimpleNamespace(source=pathlib.Path("/etc"))]}, "undeclared path"),
    ):
        _expect_exit(lambda settings=settings: finalize(**settings), message)
    _expect_exit(
        lambda: _validate(wrapper, _configuration(), [staged], stage="finalize"),
        "requires a declared base tree and initrd",
    )
    _expect_exit(
        lambda: _validate(wrapper, _configuration(), [staged], stage="incremental"),
        "unknown release stage incremental",
    )


def _check_base_configuration(wrapper, root):
    _, _, other, staged = _base_artifacts(root)

    def base(**settings):
        return _validate(wrapper, _configuration(**settings), [staged], stage="base")

    base()
    base(image_id="rules-mkosi-ab")
    base(kernel_modules_initrd=True, initrd_packages=["cryptsetup"], initrd_profiles=["lvm"])
    for settings, message in (
        ({"kernel_modules_initrd": False}, "cannot use KernelModulesInitrd=no"),
        ({"kernel_modules_initrd_include": ["virtio"]}, "cannot use KernelModulesInitrdInclude=/KernelInitrdModules="),
        ({"kernel_modules_initrd_exclude": ["drm"]}, "cannot use KernelModulesInitrdExclude="),
        ({"image_version": "1"}, "release base configuration cannot set ImageVersion="),
        ({"base_trees": [other]}, "release configuration base_trees resolves undeclared path"),
    ):
        _expect_exit(lambda settings=settings: base(**settings), message)


def _check_finalize_config_directory(wrapper, root):
    validate = wrapper.release_validation.validate_finalize_config_directory
    finalize_config = root / "finalize-config"
    finalize_config.mkdir()
    (finalize_config / "mkosi.conf").write_text("[Content]\nBootable=yes\n")
    validate(finalize_config)
    for name, is_directory in (("mkosi.initrd.conf", False), ("mkosi.initrd.conf", True), ("mkosi.initrd", True)):
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
    nested = root / "nested-finalize-config"
    (nested / "mkosi").mkdir(parents=True)
    (nested / "mkosi/mkosi.conf").write_text("[Content]\nBootable=yes\n")
    (nested / "mkosi/mkosi.initrd.conf").write_text("[Content]\nPackages=cryptsetup\n")
    _expect_exit(lambda: validate(nested), "cannot contain mkosi.initrd.conf")


def _check_staged_configuration(wrapper, root):
    configuration = root / "staged-finalize"
    configuration.mkdir()
    (configuration / "mkosi.conf").write_text("[Content]\nBootable=yes\n")
    (configuration / "mkosi.initrd.conf").write_text("[Content]\nPackages=cryptsetup\n")
    workspace = root / "staged-finalize-workspace"
    arguments = ["-C", os.fspath(configuration), "-I", os.fspath(configuration / "mkosi.conf")]
    arguments += ["--workspace-directory", os.fspath(workspace)]
    preamble = wrapper.command_line.Preamble()
    staged = wrapper._stage_configuration(preamble, arguments)
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
    # The finalization rejects the staged copy before it patches mkosi.
    _expect_exit(
        lambda: wrapper._activate_release_mode(preamble, arguments, "finalize", None, staged),
        "cannot contain mkosi.initrd.conf",
    )
    _expect_exit(
        lambda: wrapper._activate_release_mode(preamble, [], "image", None, None),
        "requires a staged -C configuration directory",
    )
    assert wrapper._stage_configuration(preamble, ["build"]) is None


if __name__ == "__main__":
    main()
