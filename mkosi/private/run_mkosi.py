#!/usr/bin/python3
"""Run mkosi after resolving Bazel paths before mkosi changes directory."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

def _load_diagnostics():
    path = Path(__file__).with_name("diagnostics.py")
    spec = importlib.util.spec_from_file_location("mkosi_diagnostics", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("diagnostic formatter cannot be loaded: {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

diagnostics = _load_diagnostics()

_EPOCH = (0, 0)
_RELEASE_PASSWD = "root:x:0:0:root:/root:/bin/sh\n"
_RELEASE_GROUP = "root:x:0:\n"
_RELEASE_HOSTS = "127.0.0.1 localhost\n::1 localhost\n"
_RELEASE_NSSWITCH = """\
passwd:     files
shadow:     files
group:      files
hosts:      files
services:   files
netgroup:   files
automount:  files

aliases:    files
ethers:     files
gshadow:    files
networks:   files
protocols:  files
publickey:  files
rpc:        files
"""
sys.dont_write_bytecode = True


_PATH_OPTIONS = {
    "-I",
    "--include",
    "-C",
    "--directory",
    "--tools-tree",
    "--extra-search-path",
    "--output-directory",
    "--workspace-directory",
    "--cache-directory",
    "--package-cache-directory",
    "--build-directory",
    "--sandbox-tree",
}


def _absolute_paths(arguments):
    result = []
    resolve_next = False
    for argument in arguments:
        if resolve_next:
            result.append(os.path.abspath(argument))
            resolve_next = False
        elif argument in _PATH_OPTIONS:
            result.append(argument)
            resolve_next = True
        elif any(argument.startswith(option + "=") for option in _PATH_OPTIONS):
            option, value = argument.split("=", 1)
            result.append(option + "=" + os.path.abspath(value))
        else:
            result.append(argument)
    if resolve_next:
        raise SystemExit("mkosi path option is missing its value")
    return result


def _materialize_tree(source, destination, executable_paths=()):
    source = Path(source)
    source_root = source.resolve(strict=True)
    executable_paths = set(executable_paths)
    destination = Path(destination)
    if destination.is_symlink():
        raise SystemExit("materialization destination is a symlink")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o755)
    os.utime(destination, _EPOCH)

    def copy_tree(source_dir, target_dir, relative_prefix):
        target_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(target_dir, 0o755)
        os.utime(target_dir, _EPOCH)
        for item in sorted(os.scandir(source_dir), key=lambda entry: entry.name):
            source_path = Path(item.path)
            target_path = target_dir / item.name
            if item.is_symlink():
                resolved = source_path.resolve(strict=True)
                if resolved.is_relative_to(source_root):
                    target_path.symlink_to(os.readlink(source_path))
                    os.utime(target_path, _EPOCH, follow_symlinks=False)
                elif resolved.is_dir():
                    copy_tree(resolved, target_path, relative_prefix / item.name)
                elif resolved.is_file():
                    shutil.copyfile(resolved, target_path)
                    os.chmod(
                        target_path,
                        0o755
                        if (relative_prefix / item.name).as_posix() in executable_paths
                        else 0o644,
                    )
                    os.utime(target_path, _EPOCH)
                else:
                    raise SystemExit("unsupported Bazel input indirection: {}".format(source_path))
            elif item.is_dir(follow_symlinks=False):
                copy_tree(source_path, target_path, relative_prefix / item.name)
            elif item.is_file(follow_symlinks=False):
                shutil.copyfile(source_path, target_path)
                os.chmod(
                    target_path,
                    0o755
                    if (relative_prefix / item.name).as_posix() in executable_paths
                    else 0o644,
                )
                os.utime(target_path, _EPOCH)
            else:
                raise SystemExit("unsupported staged entry: {}".format(source_path))
        os.chmod(target_dir, 0o755)
        os.utime(target_dir, _EPOCH)

    copy_tree(source_root, destination, Path())


def _restore_manifest_links(destination, manifest_path):
    entries = json.loads(Path(manifest_path).read_text())
    for entry in entries:
        if entry["kind"] != "symlink":
            continue
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("invalid staging manifest path")
        target = destination / relative
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            raise SystemExit("staging manifest entry is missing")
        link_target = entry["link_target"]
        if not link_target or os.path.isabs(link_target):
            raise SystemExit("invalid staging manifest link")
        target.symlink_to(link_target)
        os.utime(target, _EPOCH, follow_symlinks=False)
    directories = []
    for root, dirnames, _ in os.walk(destination, followlinks=False):
        directories.append(Path(root))
        for name in dirnames:
            path = Path(root) / name
            if not path.is_symlink():
                directories.append(path)
    for path in sorted(set(directories), reverse=True):
        os.chmod(path, 0o755)
        os.utime(path, _EPOCH)


def _extract_debian_tools(archive, extractor_path, expected_digest, destination):
    if destination.is_symlink():
        raise SystemExit("Debian tools destination is a symlink")
    if destination.exists():
        shutil.rmtree(destination)
    extractor_spec = importlib.util.spec_from_file_location(
        "mkosi_debian_extract_tree",
        extractor_path,
    )
    if extractor_spec is None or extractor_spec.loader is None:
        raise SystemExit("Debian tools extractor cannot be loaded")
    extractor = importlib.util.module_from_spec(extractor_spec)
    extractor_spec.loader.exec_module(extractor)
    extractor.extract(archive, destination, expected_digest)

def _run_mkosi(script, arguments, runner=subprocess.run):
    """Run mkosi and classify process-boundary failures without masking exit status."""
    try:
        completed = runner(
            [sys.executable, script] + arguments,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        diagnostics.fail("TOOLCHAIN_FAILURE", "mkosi executable cannot start {}: {}".format(script, error))
    if completed.returncode:
        diagnostics.fail(
            diagnostics.classify_mkosi_output(completed.stdout + completed.stderr),
            "mkosi image assembly exited with status {}".format(completed.returncode),
            completed.stdout + completed.stderr,
            exit_code=diagnostics.child_exit_code(completed.returncode),
        )
    for stream, content in ((sys.stdout, completed.stdout), (sys.stderr, completed.stderr)):
        binary_stream = getattr(stream, "buffer", None)
        if binary_stream is None:
            stream.write(content.decode(errors="replace"))
        else:
            binary_stream.write(content)


def _write_release_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, 0o644)
    os.utime(path, _EPOCH)


def _configure_release_mirror(source, workspace, arguments):
    mirror = workspace / "debian-snapshot"
    _materialize_tree(source, mirror)
    sandbox_tree = workspace / "release-sandbox"
    _write_release_file(
        sandbox_tree / "etc/apt/apt.conf.d/99rules-mkosi-release",
        'Acquire::Languages "none";\nAcquire::By-Hash "no";\n',
    )
    _write_release_file(sandbox_tree / "etc/passwd", _RELEASE_PASSWD)
    _write_release_file(sandbox_tree / "etc/group", _RELEASE_GROUP)
    _write_release_file(sandbox_tree / "etc/hosts", _RELEASE_HOSTS)
    _write_release_file(sandbox_tree / "etc/nsswitch.conf", _RELEASE_NSSWITCH)
    arguments.extend(
        [
            "--local-mirror",
            "file://" + os.fspath(mirror),
            "--sandbox-tree",
            os.fspath(sandbox_tree),
        ]
    )
    return mirror


def _configuration_paths(value):
    if isinstance(value, Path):
        yield value
    elif hasattr(value, "source"):
        source = value.source
        if source:
            yield from _configuration_paths(source)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _configuration_paths(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _configuration_paths(item)


def _validate_release_configuration(
    images,
    release_seed,
    release_source_date_epoch,
    allowed_paths,
):
    expected_seed = uuid.UUID(release_seed)
    allowed_roots = [Path(path).resolve() for path in allowed_paths]
    for config in images:
        if config.seed != expected_seed:
            raise SystemExit(
                "release configuration Seed must resolve to {}".format(expected_seed)
            )
        if config.source_date_epoch != release_source_date_epoch:
            raise SystemExit(
                "release configuration SourceDateEpoch must resolve to {}".format(
                    release_source_date_epoch
                )
            )
        for name, value in vars(config).items():
            if name in (
                "proxy_peer_certificate",
                "proxy_client_certificate",
                "proxy_client_key",
            ) and not config.proxy_url:
                continue
            for path in _configuration_paths(value):
                resolved = path.resolve()
                if not any(
                    resolved == root or resolved.is_relative_to(root)
                    for root in allowed_roots
                ):
                    raise SystemExit(
                        "release configuration {} resolves undeclared path {}".format(
                            name,
                            resolved,
                        )
                    )
    return tuple(allowed_roots)


def _activate_release_mode(
    mirror,
    release_seed,
    release_source_date_epoch,
    allowed_paths,
):
    """Mount a long Bazel path at mkosi's stable in-sandbox repository path."""
    from pathlib import Path

    import mkosi
    import mkosi.config
    import mkosi.distribution.debian
    from mkosi.context import Context
    from mkosi.distribution.debian import Installer
    from mkosi.installer import PackageManager

    mirror = os.fspath(mirror)
    source_url = "file://" + mirror
    original_context_init = Context.__init__
    original_mounts = PackageManager.mounts.__func__
    original_repositories = Installer.repositories.__func__
    original_parse_config = mkosi.config.parse_config
    validate_initial_configuration = [True]

    def repositories(cls, context, for_image=False):
        if for_image:
            return
        for repository in original_repositories(cls, context, for_image):
            if repository.url == source_url:
                yield replace(repository, url="file:///repository")
            else:
                yield repository

    def mounts(cls, context):
        result = original_mounts(cls, context)
        for index in range(len(result) - 2):
            if (
                result[index] == "--bind"
                and os.fspath(result[index + 1]) == mirror
                and result[index + 2] == "/repository"
            ):
                result[index] = "--ro-bind"
                break
        else:
            raise SystemExit("mkosi did not register the declared release mirror")
        for index in range(len(result) - 2):
            if (
                result[index] == "--ro-bind"
                and os.fspath(result[index + 1]) == mirror
                and os.fspath(result[index + 2]) == mirror
            ):
                del result[index : index + 3]
                break
        return result

    def context_init(self, *args, **kwargs):
        original_context_init(self, *args, **kwargs)
        self._rules_mkosi_release_mirror = True

    def repository(self):
        if not getattr(self, "_rules_mkosi_release_mirror", False):
            return self.workspace / "repository"
        return Path(mirror)

    def parse_config(*args, **kwargs):
        parsed = original_parse_config(*args, **kwargs)
        if validate_initial_configuration[0]:
            _validate_release_configuration(
                parsed[2],
                release_seed,
                release_source_date_epoch,
                allowed_paths,
            )
            validate_initial_configuration[0] = False
        return parsed

    def install_sandbox_trees(config, dst):
        (dst / "etc").mkdir(exist_ok=True)

        if (policy := config.tools() / "usr/share/crypto-policies/back-ends/DEFAULT").exists():
            Path(dst / "etc/crypto-policies").mkdir(exist_ok=True)
            mkosi.copy_tree(policy, dst / "etc/crypto-policies/back-ends", sandbox=config.sandbox)

        if config.sandbox_trees:
            with mkosi.complete_step("Copying in sandbox trees…"):
                for tree in config.sandbox_trees:
                    mkosi.install_tree(config, tree.source, dst, target=tree.target, preserve=False)

        if not (dst / "etc/mtab").is_symlink():
            (dst / "etc/mtab").symlink_to("../proc/self/mounts")

        Path(dst / "etc/resolv.conf").unlink(missing_ok=True)
        Path(dst / "etc/resolv.conf").touch()

        if not (dst / "etc/nsswitch.conf").exists():
            _write_release_file(dst / "etc/nsswitch.conf", _RELEASE_NSSWITCH)

        Path(dst / "etc/static").unlink(missing_ok=True)
        if (config.tools() / "etc/static").is_symlink():
            (dst / "etc/static").symlink_to((config.tools() / "etc/static").readlink())

        for directory in (
            "etc/pki/ca-trust",
            "etc/pki/tls",
            "etc/ssl",
            "etc/ca-certificates",
            "etc/pacman.d/gnupg",
            "etc/alternatives",
        ):
            (dst / directory).mkdir(parents=True, exist_ok=True)
        for filename in ("etc/shadow", "etc/gshadow", "etc/ld.so.cache"):
            (dst / filename).touch(exist_ok=True)

    def install_apt_sources(context, repositories):
        del repositories
        apt = context.root / "etc/apt"
        (apt / "sources.list").unlink(missing_ok=True)
        sources = apt / "sources.list.d"
        if sources.exists():
            for source in sources.iterdir():
                if source.is_file() and source.suffix in (".list", ".sources"):
                    source.unlink()

    Context.__init__ = context_init
    Installer.repositories = classmethod(repositories)
    PackageManager.mounts = classmethod(mounts)
    Context.repository = property(repository)
    mkosi.config.parse_config = parse_config
    mkosi.distribution.debian.install_apt_sources = install_apt_sources
    mkosi.install_sandbox_trees = install_sandbox_trees


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: run_mkosi.py MKOSI_SCRIPT [--executable-path PATH] -- [mkosi arguments]")
    script = os.path.abspath(sys.argv[1])
    preamble_end = 2
    executable_paths = []
    staging_manifest = None
    debian_tools_archive = None
    debian_tools_extractor = None
    debian_tools_sha256 = None
    kernel_preflight = None
    debian_snapshot_repository = None
    release_mirror = None
    release_seed = None
    release_source_date_epoch = None
    while preamble_end < len(sys.argv) and sys.argv[preamble_end] != "--":
        option = sys.argv[preamble_end]
        if option == "--executable-path" and preamble_end + 1 < len(sys.argv):
            executable_paths.append(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--staging-manifest" and preamble_end + 1 < len(sys.argv):
            staging_manifest = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--debian-tools-archive" and preamble_end + 1 < len(sys.argv):
            debian_tools_archive = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--debian-tools-extractor" and preamble_end + 1 < len(sys.argv):
            debian_tools_extractor = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--debian-tools-sha256" and preamble_end + 1 < len(sys.argv):
            debian_tools_sha256 = sys.argv[preamble_end + 1]
            preamble_end += 2
        elif option == "--kernel-preflight" and preamble_end + 1 < len(sys.argv):
            kernel_preflight = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--debian-snapshot-repository" and preamble_end + 1 < len(sys.argv):
            debian_snapshot_repository = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--release-seed" and preamble_end + 1 < len(sys.argv):
            release_seed = sys.argv[preamble_end + 1]
            preamble_end += 2
        elif option == "--release-source-date-epoch" and preamble_end + 1 < len(sys.argv):
            try:
                release_source_date_epoch = int(sys.argv[preamble_end + 1])
            except ValueError as error:
                raise SystemExit("release source date epoch must be an integer") from error
            preamble_end += 2
        else:
            raise SystemExit("invalid run_mkosi.py preamble")
    if preamble_end == len(sys.argv):
        raise SystemExit("run_mkosi.py preamble is missing --")
    if not kernel_preflight:
        raise SystemExit("run_mkosi.py requires --kernel-preflight")
    if os.environ.get("PYTHONPATH"):
        python_paths = os.environ["PYTHONPATH"].split(os.pathsep)
        os.environ["PYTHONPATH"] = os.pathsep.join(
            os.path.abspath(path or ".")
            for path in python_paths
        )
        sys.path[:] = [
            os.path.abspath(path) if path in python_paths else path
            for path in sys.path
        ]
    arguments = _absolute_paths(sys.argv[preamble_end + 1 :])
    diagnostics.run_kernel_preflight(kernel_preflight, "mkosi image assembly")
    debian_options = (
        debian_tools_archive,
        debian_tools_extractor,
        debian_tools_sha256,
    )
    if any(debian_options) and not all(debian_options):
        raise SystemExit("incomplete Debian tools archive configuration")
    release_options = (
        debian_snapshot_repository,
        release_seed,
        release_source_date_epoch,
    )
    if any(option is not None for option in release_options) and not all(
        option is not None for option in release_options
    ):
        raise SystemExit("incomplete release configuration")
    if all(debian_options):
        workspace = Path(arguments[arguments.index("--workspace-directory") + 1])
        tools_root = Path(arguments[arguments.index("--tools-tree") + 1])
        expected_tools_root = workspace / "debian-tools"
        if tools_root != expected_tools_root:
            raise SystemExit("Debian tools destination must be inside the mkosi workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        _extract_debian_tools(
            debian_tools_archive,
            debian_tools_extractor,
            debian_tools_sha256,
            tools_root,
        )
    if debian_snapshot_repository:
        workspace = Path(arguments[arguments.index("--workspace-directory") + 1])
        release_mirror = _configure_release_mirror(debian_snapshot_repository, workspace, arguments)
    if "-C" in arguments:
        directory = Path(arguments[arguments.index("-C") + 1])
        workspace = Path(arguments[arguments.index("--workspace-directory") + 1])
        materialized = workspace / "staging-root"
        _materialize_tree(directory, materialized, executable_paths)
        if staging_manifest:
            _restore_manifest_links(materialized, staging_manifest)
        arguments[arguments.index("-C") + 1] = os.fspath(materialized)
        for option in ("-I", "--include"):
            for index, argument in enumerate(arguments):
                if argument.startswith(os.fspath(directory) + os.sep):
                    arguments[index] = os.fspath(materialized) + argument[len(os.fspath(directory)) :]
    if release_mirror:
        allowed_paths = []
        for index, argument in enumerate(arguments):
            if argument in _PATH_OPTIONS and index + 1 < len(arguments):
                allowed_paths.append(arguments[index + 1])
        _activate_release_mode(
            os.fspath(release_mirror),
            release_seed,
            release_source_date_epoch,
            allowed_paths,
        )
    _run_mkosi(script, arguments)


if __name__ == "__main__":
    main()
