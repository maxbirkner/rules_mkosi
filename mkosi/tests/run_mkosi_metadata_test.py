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


def main():
    wrapper = _load_wrapper(sys.argv[1])
    root = pathlib.Path(os.environ["TEST_TMPDIR"])
    first = _prepare(root, "first", 0o600, 946684800)
    second = _prepare(root, "second", 0o644, 1893456000)
    wrapper._materialize_tree(root / "first-root-link", root / "out-first")
    wrapper._materialize_tree(root / "second-root-link", root / "out-second")
    _assert_normalized(root / "out-first")
    _assert_normalized(root / "out-second")
    assert (root / "out-first/file-target").read_bytes() == (root / "out-second/file-target").read_bytes()
    assert first != second

    restored = root / "restored"
    restored.mkdir()
    (restored / "target").write_text("target\n")
    (restored / "link").write_text("materialized link\n")
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "kind": "symlink",
                    "link_target": "target",
                    "path": "link",
                },
            ]
        )
    )
    wrapper._restore_manifest_links(restored, manifest)
    assert (restored / "link").is_symlink()
    assert (restored / "link").lstat().st_mtime == 0

    repository = root / "repository"
    (repository / "dists/trixie/main").mkdir(parents=True)
    (repository / "dists/trixie/main/Release").write_text("locked metadata\n")
    arguments = []
    mirror = wrapper._configure_release_mirror(repository, root / "workspace", arguments)
    assert arguments == [
        "--local-mirror",
        "file://" + os.fspath(mirror),
        "--sandbox-tree",
        os.fspath(root / "workspace/release-sandbox"),
    ]
    assert (mirror / "dists/trixie/main/Release").read_text() == "locked metadata\n"
    assert mirror.stat().st_mtime == 0
    assert (
        root / "workspace/release-sandbox/etc/apt/apt.conf.d/99rules-mkosi-release"
    ).read_text() == 'Acquire::Languages "none";\nAcquire::By-Hash "no";\n'
    assert (root / "workspace/release-sandbox/etc/passwd").read_text() == wrapper._RELEASE_PASSWD
    assert (root / "workspace/release-sandbox/etc/group").read_text() == wrapper._RELEASE_GROUP
    assert (root / "workspace/release-sandbox/etc/hosts").read_text() == wrapper._RELEASE_HOSTS
    assert (
        root / "workspace/release-sandbox/etc/nsswitch.conf"
    ).read_text() == wrapper._RELEASE_NSSWITCH
    release_setup = inspect.getsource(wrapper._activate_release_mode)
    for host_file in ("/etc/passwd", "/etc/group", "/etc/hosts"):
        assert host_file not in release_setup
    for section in ("Match", "TriggerMatch"):
        try:
            wrapper._validate_release_ini_entry(section)
        except SystemExit as error:
            assert "host-dependent matching" in str(error)
        else:
            raise AssertionError("host-dependent match was accepted")
    wrapper._validate_release_ini_entry("Content")

    seed = "00000000-0000-4000-8000-000000000015"
    wrapper._validate_release_configuration(
        [types.SimpleNamespace(seed=uuid.UUID(seed), source_date_epoch=0)],
        seed,
        0,
        "debian",
        "trixie",
        "20250814T000000Z",
        [root],
    )
    snapshot_components = ("main", "non-free-firmware")
    assert wrapper._release_apt_components([], snapshot_components) == ("main",)
    assert wrapper._release_apt_components(
        ["non-free-firmware", "main", "non-free-firmware"],
        snapshot_components,
    ) == snapshot_components
    wrapper._validate_release_configuration(
        [
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                repositories=["non-free-firmware"],
            )
        ],
        seed,
        0,
        "debian",
        "trixie",
        "20250814T000000Z",
        [root],
        release_components=snapshot_components,
    )
    for repositories, components in (
        (["non-free-firmware"], ("main",)),
        (["contrib"], snapshot_components),
    ):
        try:
            wrapper._validate_release_configuration(
                [
                    types.SimpleNamespace(
                        seed=uuid.UUID(seed),
                        source_date_epoch=0,
                        repositories=repositories,
                    )
                ],
                seed,
                0,
                "debian",
                "trixie",
                "20250814T000000Z",
                [root],
                release_components=components,
            )
        except SystemExit as error:
            assert "absent from the Debian snapshot: " + repositories[0] in str(error), error
        else:
            raise AssertionError("Repositories={} was accepted".format(repositories))
    safe_extra = root / "mkosi.extra"
    wrapper._validate_release_configuration(
        [
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                extra_trees=[types.SimpleNamespace(source=safe_extra)],
            )
        ],
        seed,
        0,
        "debian",
        "trixie",
        "20250814T000000Z",
        [root],
        safe_extra,
    )
    for setting, value, message in (
        ("secure_boot", True, "SecureBoot"),
        ("unified_kernel_images", types.SimpleNamespace(value="yes"), "UnifiedKernelImages"),
        ("bootloader", types.SimpleNamespace(value="systemd-boot"), "UEFI Bootloader"),
    ):
        configuration = types.SimpleNamespace(
            seed=uuid.UUID(seed),
            source_date_epoch=0,
            **{setting: value},
        )
        try:
            wrapper._validate_release_configuration(
                [configuration],
                seed,
                0,
                "debian",
                "trixie",
                "20250814T000000Z",
                [root],
                None,
                "bios",
            )
        except SystemExit as error:
            assert message in str(error)
        else:
            raise AssertionError("{} was accepted for BIOS".format(setting))

    for configuration, message in (
        (types.SimpleNamespace(seed=uuid.uuid4(), source_date_epoch=0), "Seed"),
        (types.SimpleNamespace(seed=uuid.UUID(seed), source_date_epoch=None), "SourceDateEpoch"),
    ):
        try:
            wrapper._validate_release_configuration(
                [configuration],
                seed,
                0,
                "debian",
                "trixie",
                "20250814T000000Z",
                [root],
            )
        except SystemExit as error:
            assert message in str(error)
        else:
            raise AssertionError("non-deterministic release configuration was accepted")
    try:
        wrapper._validate_release_configuration(
            [
                types.SimpleNamespace(
                    seed=uuid.UUID(seed),
                    source_date_epoch=0,
                    skeleton_trees=[types.SimpleNamespace(source=pathlib.Path("/etc"))],
                )
            ],
            seed,
            0,
            "debian",
            "trixie",
            "20250814T000000Z",
            [root],
        )
    except SystemExit as error:
        assert "undeclared path" in str(error)
    else:
        raise AssertionError("release configuration accepted an undeclared tree")
    for configuration, message in (
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                proxy_peer_certificate=pathlib.Path("/etc/ssl/certs/ca-certificates.crt"),
            ),
            "undeclared path",
        ),
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                extra_trees=[types.SimpleNamespace(source=root)],
            ),
            "extra_trees is not supported",
        ),
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                microcode_host=True,
            ),
            "microcode_host is not supported",
        ),
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                kernel_modules_include_host=True,
            ),
            "kernel_modules_include_host is not supported",
        ),
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                kernel_modules_initrd_include_host=True,
            ),
            "kernel_modules_initrd_include_host is not supported",
        ),
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                kernel_modules_include=["host"],
            ),
            "kernel_modules_include cannot include host modules",
        ),
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                kernel_modules_initrd_include=["host"],
            ),
            "kernel_modules_initrd_include cannot include host modules",
        ),
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                distribution=types.SimpleNamespace(value="ubuntu"),
                release="noble",
                snapshot="20250814T000000Z",
            ),
            "must resolve to debian trixie snapshot",
        ),
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                secure_boot_key_source=types.SimpleNamespace(source="engine"),
            ),
            "secure_boot_key_source is not supported",
        ),
        (
            types.SimpleNamespace(
                seed=uuid.UUID(seed),
                source_date_epoch=0,
                incremental=types.SimpleNamespace(value="yes"),
            ),
            "incremental mode is not supported",
        ),
    ):
        try:
            wrapper._validate_release_configuration(
                [configuration],
                seed,
                0,
                "debian",
                "trixie",
                "20250814T000000Z",
                [root],
            )
        except SystemExit as error:
            assert message in str(error)
        else:
            raise AssertionError("cache-unsafe release configuration was accepted")
    _check_two_stage_release(wrapper, root, seed)
    print("materialized metadata and relative links are deterministic")


def _expect_exit(function, message):
    try:
        function()
    except SystemExit as error:
        assert message in str(error), error
    else:
        raise AssertionError("expected failure containing {!r}".format(message))


def _check_two_stage_release(wrapper, root, seed):
    arguments = []
    wrapper._configure_release_sandbox(root / "finalize-workspace", arguments)
    assert arguments == ["--sandbox-tree", os.fspath(root / "finalize-workspace/release-sandbox")]
    assert (root / "finalize-workspace/release-sandbox/etc/passwd").read_text() == wrapper._RELEASE_PASSWD

    # mkosi's "default" initrd constant is not a path relative to the action's working directory.
    assert wrapper._absolute_paths(["--initrd=default", "--initrd", "default", "--base-tree", "base.tar"]) == [
        "--initrd=default",
        "--initrd",
        "default",
        "--base-tree",
        os.path.abspath("base.tar"),
    ]
    assert wrapper._absolute_paths(["--initrd", "initrd"]) == ["--initrd", os.path.abspath("initrd")]
    argv = ["--release-seed", "x", "--", "--output-directory", "out"]
    assert wrapper._mkosi_option_value(argv, "--output-directory") == "out"
    _expect_exit(
        lambda: wrapper._mkosi_option_value(["--output-directory", "preamble", "--"], "--output-directory"),
        "expected exactly one mkosi --output-directory argument",
    )

    assert wrapper._release_stage(False, None, None, None, None) is None
    assert wrapper._release_stage(True, "repository", None, None, None) == "image"
    assert wrapper._release_stage(True, "repository", None, None, "initrd") == "base"
    assert wrapper._release_stage(True, None, "root.tar", "initrd", None) == "finalize"
    for options, message in (
        ((True, None, "root.tar", None, None), "requires both --release-base-tree and --release-initrd"),
        ((True, "repository", "root.tar", "initrd", None), "cannot use the Debian snapshot or produce a base"),
        ((True, None, "root.tar", "initrd", "initrd"), "cannot use the Debian snapshot or produce a base"),
        ((True, None, None, None, "initrd"), "a release base requires the Debian snapshot repository"),
        ((False, "repository", None, None, None), "incomplete release configuration"),
        ((False, None, "root.tar", "initrd", None), "incomplete release configuration"),
        ((True, None, None, None, None), "incomplete release configuration"),
    ):
        _expect_exit(lambda options=options: wrapper._release_stage(*options), message)

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

    base_tree = root / "base/root.tar"
    base_tree.parent.mkdir()
    base_tree.write_bytes(b"tar")
    base_initrd = root / "base/initrd"
    base_initrd.write_bytes(b"initrd")
    other = root / "other.tar"
    other.write_bytes(b"tar")
    staged = root / "staged"
    staged.mkdir()

    def finalize(**settings):
        configuration = dict(
            seed=uuid.UUID(seed),
            source_date_epoch=0,
            distribution=types.SimpleNamespace(value="debian"),
            release="trixie",
            snapshot=None,
            base_trees=[base_tree],
            initrds=[base_initrd],
        )
        configuration.update(settings)
        return wrapper._validate_release_configuration(
            [types.SimpleNamespace(**configuration)],
            seed,
            0,
            "debian",
            "trixie",
            "20250814T000000Z",
            [staged],
            release_stage="finalize",
            base_tree=base_tree,
            base_initrd=base_initrd,
        )

    # The declared base artifacts are allowed although they are outside every staged path option.
    assert base_tree.resolve() in finalize()
    finalize(cacheonly=types.SimpleNamespace(value="always"))
    finalize(snapshot="20250814T000000Z")
    for settings, message in (
        ({"snapshot": "20260101T000000Z"}, "must resolve to debian trixie snapshot"),
        ({"packages": ["vim"]}, "cannot use Packages="),
        ({"build_packages": ["gcc"]}, "cannot use BuildPackages="),
        ({"volatile_packages": ["vim"]}, "cannot use VolatilePackages="),
        ({"remove_packages": ["apt"]}, "cannot use RemovePackages="),
        ({"package_directories": [staged]}, "cannot use PackageDirectories="),
        ({"base_trees": []}, "BaseTrees= must resolve to exactly the declared base tree"),
        ({"base_trees": [base_tree, other]}, "BaseTrees= must resolve to exactly the declared base tree"),
        ({"base_trees": [other]}, "BaseTrees= must resolve to exactly the declared base tree"),
        ({"initrds": []}, "Initrds= must resolve to exactly the declared base initrd"),
        ({"initrds": [base_initrd, other]}, "Initrds= must resolve to exactly the declared base initrd"),
        ({"cacheonly": types.SimpleNamespace(value="auto")}, "CacheOnly= must resolve to always"),
        ({"skeleton_trees": [types.SimpleNamespace(source=pathlib.Path("/etc"))]}, "undeclared path"),
    ):
        _expect_exit(lambda settings=settings: finalize(**settings), message)
    _expect_exit(
        lambda: wrapper._validate_release_configuration(
            [types.SimpleNamespace(seed=uuid.UUID(seed), source_date_epoch=0)],
            seed,
            0,
            "debian",
            "trixie",
            "20250814T000000Z",
            [staged],
            release_stage="finalize",
        ),
        "requires a declared base tree and initrd",
    )

    def base(**settings):
        return wrapper._validate_release_configuration(
            [types.SimpleNamespace(seed=uuid.UUID(seed), source_date_epoch=0, **settings)],
            seed,
            0,
            "debian",
            "trixie",
            "20250814T000000Z",
            [staged],
            release_stage="base",
        )

    base()
    base(image_id="rules-mkosi-ab")
    _expect_exit(lambda: base(image_version="1"), "release base configuration cannot set ImageVersion=")
    _expect_exit(
        lambda: base(base_trees=[other]),
        "release configuration base_trees resolves undeclared path",
    )
    _expect_exit(
        lambda: wrapper._validate_release_configuration(
            [types.SimpleNamespace(seed=uuid.UUID(seed), source_date_epoch=0)],
            seed,
            0,
            "debian",
            "trixie",
            "20250814T000000Z",
            [staged],
            release_stage="incremental",
        ),
        "unknown release stage incremental",
    )
    release_setup = inspect.getsource(wrapper._deterministic_make_tar)
    assert '"--sort=name"' in release_setup
    assert '"--sparse"' not in release_setup


if __name__ == "__main__":
    main()
