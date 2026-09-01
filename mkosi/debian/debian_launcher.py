"""Execute a Debian build tool from an authenticated, isolated package tree."""

import importlib.util
import json
import os
import pathlib
import posixpath
import shutil
import stat
import subprocess
import sys
from typing import NamedTuple

import click
from python.runfiles import runfiles


TOOLS = {
    "shell": "/bin/sh",
    "apt-get": "/usr/bin/apt-get",
    "dpkg": "/usr/bin/dpkg",
    "debugfs": "/usr/sbin/debugfs",
    "systemd-repart": "/usr/bin/systemd-repart",
    "mkfs.ext4": "/usr/sbin/mkfs.ext4",
    "mkfs.fat": "/usr/sbin/mkfs.fat",
    "mkfs.btrfs": "/usr/sbin/mkfs.btrfs",
    "sfdisk": "/usr/sbin/sfdisk",
    "parted": "/usr/sbin/parted",
    "grub-install": "/usr/sbin/grub-install",
    "bootctl": "/usr/bin/bootctl",
    "objcopy": "/usr/bin/objcopy",
    "openssl": "/usr/bin/openssl",
    "sqv": "/usr/bin/sqv",
}

_DETERMINISTIC_ENVIRONMENT = (
    "SOURCE_DATE_EPOCH",
    "SYSTEMD_REPART_MKFS_OPTIONS_EXT4",
)
_MOUNT_ROOTS = ("/root", "/tmp", "/proc", "/dev", "/workspace", "/inputs", "/outputs")
_RUNFILES = {
    "archive": "mkosi_debian_tools/flat.tar",
    "config": "mkosi_debian_tools/launcher_config.json",
    "extractor": "rules_mkosi/mkosi/debian/extract_tree.py",
    "namespace_runner": "mkosi_debian_tools/namespace_runner",
}
sys.dont_write_bytecode = True


class RuntimeFiles(NamedTuple):
    archive: str
    archive_sha256: str
    extractor: str
    namespace_runner: str


def _tool_environment():
    environment = {"PATH": "", "HOME": "/root"}
    for name in _DETERMINISTIC_ENVIRONMENT:
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def _inside_root(root, path):
    root = os.path.realpath(root)
    resolved = os.path.realpath(path)
    return resolved == root or resolved.startswith(root + os.sep)


def _require_directory(root, relative, allow_symlink=False):
    path = os.path.join(root, relative.lstrip("/"))
    if (
        not os.path.isdir(path)
        or (os.path.islink(path) and not allow_symlink)
        or not _inside_root(root, path)
    ):
        raise RuntimeError("Debian tools root has an invalid directory: %s" % relative)


def _require_executable(root, relative, description):
    path = os.path.join(root, relative.lstrip("/"))
    if (
        not os.path.isfile(path)
        or not os.access(path, os.X_OK)
        or not _inside_root(root, path)
    ):
        raise RuntimeError("%s is missing or not executable: %s" % (description, relative))
    return path


def _validate_root(root, tool):
    if not os.path.isdir(root) or os.path.islink(root):
        raise RuntimeError("Debian tools extraction did not produce a physical root")
    for relative in _MOUNT_ROOTS + ("/etc", "/usr", "/usr/bin", "/usr/sbin"):
        _require_directory(root, relative)

    bundle = os.path.join(root, "etc/ssl/certs/ca-certificates.crt")
    if (
        not os.path.isfile(bundle)
        or os.path.islink(bundle)
        or os.path.getsize(bundle) == 0
        or not _inside_root(root, bundle)
    ):
        raise RuntimeError("packaged CA bundle is missing or invalid: %s" % bundle)

    loader = None
    for candidate in (
        "lib64/ld-linux-x86-64.so.2",
        "lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
        "usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
    ):
        path = os.path.join(root, candidate)
        if os.path.isfile(path) and os.access(path, os.X_OK) and _inside_root(root, path):
            loader = path
            break
    if loader is None:
        raise RuntimeError("Debian bootstrap loader is missing from extracted root")

    if tool not in TOOLS.values():
        raise RuntimeError("unknown or unmapped Debian tool: %s" % tool)
    executable = None
    for mapped_tool in TOOLS.values():
        mapped_executable = _require_executable(root, mapped_tool, "mapped Debian executable")
        if mapped_tool == tool:
            executable = mapped_executable
    for library_directory in (
        "/usr/lib/x86_64-linux-gnu",
        "/lib/x86_64-linux-gnu",
        "/usr/lib/x86_64-linux-gnu/systemd",
        "/usr/lib/systemd",
        "/usr/lib64",
    ):
        _require_directory(root, library_directory, allow_symlink=library_directory.startswith("/lib"))
    return loader, executable


def _canonical_destination(destination):
    if not destination.startswith("/") or "\x00" in destination:
        raise RuntimeError("namespace destination must be absolute: %s" % destination)
    if posixpath.normpath(destination) != destination:
        raise RuntimeError("namespace destination is not canonical: %s" % destination)
    parts = destination.split("/")
    if any(part in ("", ".", "..") for part in parts[1:]):
        raise RuntimeError("namespace destination contains unsafe path components: %s" % destination)
    return destination


def _under(destination, parent):
    return destination == parent or destination.startswith(parent + "/")


def _validate_binds(arguments):
    ro_binds = []
    rw_binds = []
    destinations = []
    while arguments and arguments[0] in ("--ro-bind", "--rw-bind"):
        kind = arguments.pop(0)
        if not arguments or ":" not in arguments[0]:
            raise RuntimeError("%s requires SRC:DEST" % kind)
        source, destination = arguments.pop(0).split(":", 1)
        if not source.startswith("/") or "\x00" in source:
            raise RuntimeError("namespace bind source must be absolute: %s" % source)
        source = os.path.realpath(source)
        if not os.path.exists(source):
            raise FileNotFoundError("namespace bind source is missing: %s" % source)
        destination = _canonical_destination(destination)
        if destination in ("/",) + tuple(_MOUNT_ROOTS):
            raise RuntimeError("namespace bind destination is a reserved mount root: %s" % destination)
        source_stat = os.stat(source)
        bind = (
            source,
            destination,
            source_stat.st_dev,
            source_stat.st_ino,
            stat.S_ISDIR(source_stat.st_mode),
        )
        if kind == "--ro-bind":
            if not _under(destination, "/inputs"):
                raise RuntimeError("read-only namespace binds must be under /inputs: %s" % destination)
            ro_binds.append(bind)
        else:
            if not (_under(destination, "/workspace") or _under(destination, "/outputs")):
                raise RuntimeError("read-write namespace binds must be under /workspace or /outputs: %s" % destination)
            rw_binds.append(bind)
        for prior in destinations:
            if destination == prior or _under(destination, prior) or _under(prior, destination):
                raise RuntimeError("namespace bind destinations overlap: %s and %s" % (prior, destination))
        destinations.append(destination)
    return ro_binds, rw_binds


def _prepare_mountpoint(base, destination, source_is_directory):
    relative = destination.lstrip("/").split("/")
    current = base
    for part in relative[:-1]:
        current = os.path.join(current, part)
        if os.path.lexists(current):
            if not os.path.isdir(current) or os.path.islink(current):
                raise RuntimeError("namespace mount parent is not a directory: %s" % destination)
        else:
            os.mkdir(current)
        os.chmod(current, 0o755)
    path = os.path.join(base, *relative)
    if os.path.lexists(path):
        if source_is_directory and os.path.isdir(path) and not os.path.islink(path):
            return
        raise RuntimeError("namespace mount destination has the wrong type: %s" % destination)
    if source_is_directory:
        os.mkdir(path)
        os.chmod(path, 0o755)
    else:
        pathlib.Path(path).touch()
        os.chmod(path, 0o644)



def _private_scratch():
    scratch_parent = os.environ.get("MKOSI_DEBIAN_TOOLS_SCRATCH") or os.environ.get("TEST_TMPDIR")
    if not scratch_parent:
        raise RuntimeError("MKOSI_DEBIAN_TOOLS_SCRATCH or TEST_TMPDIR is required")
    scratch_parent = os.path.abspath(scratch_parent)
    current = os.path.sep
    for component in scratch_parent.strip(os.path.sep).split(os.path.sep):
        current = os.path.join(current, component)
        if os.path.islink(current):
            raise RuntimeError("invalid action-private Debian tools scratch directory: %s" % scratch_parent)
    if os.path.lexists(scratch_parent):
        if os.path.islink(scratch_parent) or not os.path.isdir(scratch_parent):
            raise RuntimeError("invalid action-private Debian tools scratch directory: %s" % scratch_parent)
    else:
        os.makedirs(scratch_parent, mode=0o700)
    if os.path.islink(scratch_parent) or not os.path.isdir(scratch_parent):
        raise RuntimeError("invalid action-private Debian tools scratch directory: %s" % scratch_parent)
    entries = [entry for entry in os.listdir(scratch_parent) if entry != ".in-use"]
    if entries:
        raise RuntimeError("Debian tools scratch directory must be empty: %s" % scratch_parent)
    return scratch_parent


def _required_runfile(resolver, logical, executable=False):
    path = resolver.Rlocation(logical)
    valid = path and os.path.isfile(path)
    if not valid or (executable and not os.access(path, os.X_OK)):
        raise RuntimeError("Debian launcher runfile is missing: %s" % logical)
    return path


def _runtime_files():
    resolver = runfiles.Create()
    if resolver is None:
        raise RuntimeError("unable to initialize Debian launcher runfiles")
    config_path = _required_runfile(resolver, _RUNFILES["config"])
    with open(config_path, encoding="utf-8") as config_file:
        config = json.load(config_file)
    if config.get("format_version") != "debian-launcher-v1":
        raise RuntimeError("unsupported Debian launcher configuration")
    archive_sha256 = config.get("archive_sha256", "")
    if len(archive_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in archive_sha256
    ):
        raise RuntimeError("Debian launcher archive digest is invalid")
    return RuntimeFiles(
        archive=_required_runfile(resolver, _RUNFILES["archive"]),
        archive_sha256=archive_sha256,
        extractor=_required_runfile(resolver, _RUNFILES["extractor"]),
        namespace_runner=_required_runfile(
            resolver,
            _RUNFILES["namespace_runner"],
            executable=True,
        ),
    )


def _extract_root(archive, expected_digest, tool, binds, extractor_path):
    if not expected_digest:
        raise RuntimeError("Debian tools archive digest is required")
    if os.environ.get("MKOSI_DEBIAN_TOOLS_SCRATCH_FORMAT", "physical-v5") != "physical-v5":
        raise RuntimeError("unsupported Debian tools scratch format")
    scratch_parent_value = os.environ.get("MKOSI_DEBIAN_TOOLS_SCRATCH") or os.environ.get(
        "TEST_TMPDIR"
    )
    if not scratch_parent_value:
        raise RuntimeError("MKOSI_DEBIAN_TOOLS_SCRATCH or TEST_TMPDIR is required")
    scratch_parent_hint = os.path.abspath(scratch_parent_value)
    scratch_was_present = os.path.lexists(scratch_parent_hint)
    scratch_parent = _private_scratch()
    lock = os.path.join(scratch_parent, ".in-use")
    try:
        os.mkdir(lock, 0o700)
    except FileExistsError:
        raise RuntimeError("Debian tools scratch directory is already in use: %s" % scratch_parent)
    root = os.path.join(scratch_parent, "root")
    try:
        if os.path.lexists(root):
            raise RuntimeError("preexisting Debian tools scratch root is forbidden: %s" % root)
        partial = os.path.join(scratch_parent, ".partial")
        os.mkdir(partial, 0o700)
        try:
            extractor_path = os.path.realpath(extractor_path)
            spec = importlib.util.spec_from_file_location("mkosi_debian_extract_tree", extractor_path)
            if spec is None or spec.loader is None:
                raise RuntimeError("Debian tools extractor cannot be loaded: %s" % extractor_path)
            extractor = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(extractor)
            extractor.extract(archive, partial, expected_digest)
            _validate_root(partial, tool)
            for _, destination, _, _, source_is_directory in binds[0] + binds[1]:
                _prepare_mountpoint(partial, destination, source_is_directory)
            extractor.set_deterministic_metadata(partial)
            marker = os.path.join(partial, ".complete")
            with open(marker, "w", encoding="utf-8") as complete:
                complete.write("mkosi-debian-tools-v1\n" + expected_digest + "\n")
                os.chmod(marker, 0o644)
                os.utime(marker, (0, 0))
                complete.flush()
                os.fsync(complete.fileno())
            os.utime(partial, (0, 0))
            os.replace(partial, root)
        except Exception:
            shutil.rmtree(partial, ignore_errors=True)
            raise
    finally:
        os.rmdir(lock)
        if not scratch_was_present and not os.path.lexists(root):
            try:
                os.rmdir(scratch_parent)
            except OSError:
                pass
    return root


def _runtime_directory(parent, name, mode=0o700):
    path = os.path.join(parent, name)
    os.mkdir(path, mode)
    os.chmod(path, mode)
    return path


def _run(
    tool,
    arguments,
    root,
    ro_binds,
    rw_binds,
    scratch_parent,
    namespace_runner,
):
    runtime = os.path.join(scratch_parent, ".runtime")
    os.mkdir(runtime, 0o700)
    try:
        workspace = _runtime_directory(runtime, "workspace")
        outputs = _runtime_directory(runtime, "outputs")
        home = _runtime_directory(runtime, "home")
        for _, destination, _, _, source_is_directory in rw_binds:
            base = workspace if _under(destination, "/workspace") else outputs
            prefix = "/workspace" if base == workspace else "/outputs"
            _prepare_mountpoint(
                base,
                destination[len(prefix):] or "/",
                source_is_directory,
            )

        if not os.path.isfile(namespace_runner) or not os.access(namespace_runner, os.X_OK):
            raise RuntimeError("static Debian namespace runner is missing")
        loader, _ = _validate_root(root, tool)
        loader_relative = "/" + os.path.relpath(loader, root)
        mount_arguments = []
        all_binds = ro_binds + rw_binds
        for index, bind in enumerate(all_binds):
            option = "--ro-bind" if index < len(ro_binds) else "--rw-bind"
            mount_arguments.extend(
                [
                    option,
                    bind[0],
                    bind[1],
                    str(bind[2]),
                    str(bind[3]),
                    "dir" if bind[4] else "file",
                ]
            )
        command = [
            namespace_runner,
            root,
            workspace,
            outputs,
            home,
            loader_relative,
            tool,
        ] + mount_arguments + ["--"] + arguments
        return subprocess.run(
            command,
            env=_tool_environment(),
        ).returncode
    finally:
        shutil.rmtree(runtime, ignore_errors=True)


class _ToolPath(click.ParamType):
    name = "tool"

    def convert(self, value, param, ctx):
        if value not in TOOLS.values():
            self.fail("unknown or unmapped Debian tool: %s" % value, param, ctx)
        return value


class _LauncherSetupError(click.ClickException):
    exit_code = 1

    def show(self, file=None):
        click.echo("Debian launcher setup failed: %s" % self.message, file=file, err=True)


def _launch(
    *,
    tool: str,
    tool_arguments: tuple[str, ...],
    validate_only: bool,
    output: pathlib.Path | None,
    ro_bind_specs: tuple[str, ...],
    rw_bind_specs: tuple[str, ...],
) -> int:
    arguments = []
    for option, specifications in (
        ("--ro-bind", ro_bind_specs),
        ("--rw-bind", rw_bind_specs),
    ):
        for specification in specifications:
            arguments.extend([option, specification])
    ro_binds, rw_binds = _validate_binds(arguments)
    runtime = _runtime_files()
    root = _extract_root(
        runtime.archive,
        runtime.archive_sha256,
        tool,
        (ro_binds, rw_binds),
        runtime.extractor,
    )
    if validate_only:
        return 0
    scratch_parent = os.path.dirname(root)
    status = _run(
        tool,
        list(tool_arguments),
        root,
        ro_binds,
        rw_binds,
        scratch_parent,
        runtime.namespace_runner,
    )
    if output:
        with open(output, "w", encoding="utf-8") as version:
            version.write("Debian tool probe: %s\n" % tool)
    return status


@click.command(
    name="debian-launcher",
    context_settings={"allow_interspersed_args": False},
)
@click.option(
    "--validate-only",
    is_flag=True,
    help="Authenticate, extract, and validate the tools tree without execution.",
)
@click.option(
    "--write-version",
    "output",
    type=click.Path(path_type=pathlib.Path, dir_okay=False),
    metavar="OUTPUT",
    help="Write the successful tool probe identity to OUTPUT.",
)
@click.option(
    "--ro-bind",
    "ro_bind_specs",
    multiple=True,
    metavar="SRC:DEST",
    help="Mount SRC read-only below /inputs.",
)
@click.option(
    "--rw-bind",
    "rw_bind_specs",
    multiple=True,
    metavar="SRC:DEST",
    help="Mount SRC read-write below /workspace or /outputs.",
)
@click.argument("tool", type=_ToolPath())
@click.argument("tool_arguments", nargs=-1, type=click.UNPROCESSED)
def cli(
    validate_only: bool,
    output: pathlib.Path | None,
    ro_bind_specs: tuple[str, ...],
    rw_bind_specs: tuple[str, ...],
    tool: str,
    tool_arguments: tuple[str, ...],
) -> None:
    """Execute an allowlisted tool inside the authenticated Debian root."""
    try:
        status = _launch(
            tool=tool,
            tool_arguments=tool_arguments,
            validate_only=validate_only,
            output=output,
            ro_bind_specs=ro_bind_specs,
            rw_bind_specs=rw_bind_specs,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise _LauncherSetupError(str(error)) from error
    if status:
        raise click.exceptions.Exit(status)


if __name__ == "__main__":
    cli(prog_name="debian-launcher")
