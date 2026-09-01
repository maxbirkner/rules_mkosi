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
    print("materialized metadata and relative links are deterministic")


if __name__ == "__main__":
    main()
