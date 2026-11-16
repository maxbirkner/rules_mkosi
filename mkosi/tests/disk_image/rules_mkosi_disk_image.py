"""Reads the GPT partitions of disk images and the files of their ext4 root file systems, for image tests.

The tests of rules_mkosi and of its e2e/smoke consumer module import this module as rules_mkosi_disk_image from
@rules_mkosi//mkosi/tests/disk_image. GPTs are read with the validating reader of the partition metadata projection,
partition types are those of mkosi/private/gpt_partitions.py, and file systems are read with debugfs from the pinned
Debian tools launcher, @mkosi_debian_tools//:launcher, which the test passes in.
"""

import errno
import os
import runpy
import subprocess
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path

_PRIVATE = Path(__file__).parents[2] / "private"
_load_sibling = runpy.run_path(str(_PRIVATE / "sibling_loader.py"))["load_sibling"]

# The partition type GUIDs of mkosi/private/gpt_partitions.py, such as gpt_partitions.root_types("arm64").verity.
gpt_partitions: types.ModuleType = _load_sibling(str(_PRIVATE / "gpt_partitions.py"), "gpt_partitions")
_partition_metadata: types.ModuleType = _load_sibling(str(_PRIVATE / "partition_metadata.py"), "partition_metadata")

_CHUNK = 1024 * 1024
# The launcher finds its own runfiles through these; debugfs runs without the host's PATH.
_RUNFILES_VARIABLES = ("RUNFILES_DIR", "RUNFILES_MANIFEST_FILE", "RUNFILES_MANIFEST_ONLY")
_FILE_SYSTEM = "/inputs/filesystem.img"
# The superblock magic numbers of ext2/3/4, at byte 1080, and of EROFS, at byte 1024.
_EXT4_MAGIC = b"\x53\xef"
_EROFS_MAGIC = b"\xe2\xe1\xf5\xe0"


@dataclass(frozen=True)
class Partition:
    """One used entry of a GPT partition table."""

    # The 1-based index of the entry in the partition table.
    number: int
    # The lowercase partition type GUID.
    type_guid: str
    label: str
    start_bytes: int
    size_bytes: int


def list_partitions(image: str | os.PathLike[str]) -> list[Partition]:
    """Returns the used partitions of the GPT of a disk image, in table order.

    Raises:
        ValueError: If the image has no valid GPT, its two copies disagree, or a partition is out of range,
            overlapping or not 1 MiB aligned.
    """
    _, entries = _partition_metadata.read_partitions(image)
    return [
        Partition(
            number=entry["number"],
            type_guid=entry["type_guid"],
            label=entry["label"],
            start_bytes=entry["start_bytes"],
            size_bytes=entry["size_bytes"],
        )
        for entry in entries
    ]


def find_root_partition(image: str | os.PathLike[str], architecture: str = "amd64") -> Partition:
    """Returns the one populated root partition of a Debian architecture, such as arm64, of a disk image.

    Inactive A/B slots, which systemd-sysupdate labels _empty, are not populated.

    Raises:
        AssertionError: If the image has no or several populated root partitions of the architecture.
        ValueError: If the image has no valid GPT or the architecture is not supported.
    """
    root_type = gpt_partitions.root_types(architecture).root
    roots = [
        partition
        for partition in list_partitions(image)
        if partition.type_guid == root_type and partition.label != gpt_partitions.EMPTY_SLOT_LABEL
    ]
    if len(roots) != 1:
        raise AssertionError("expected one populated {} root partition: {}".format(architecture, roots))
    return roots[0]


def extract_partition(image: str | os.PathLike[str], partition: Partition, destination: Path) -> None:
    """Copies a partition of a disk image to the file destination, keeping the holes of a sparse image.

    Raises:
        AssertionError: If the image ends before the partition.
    """
    end = partition.start_bytes + partition.size_bytes
    with open(image, "rb") as source, destination.open("wb") as output:
        if os.fstat(source.fileno()).st_size < end:
            raise AssertionError("partition {} is truncated".format(partition.number))
        output.truncate(partition.size_bytes)
        position = partition.start_bytes
        while position < end:
            data, hole = _next_data(source.fileno(), position, end)
            while data < hole:
                chunk = os.pread(source.fileno(), min(_CHUNK, hole - data), data)
                if not chunk:
                    raise AssertionError("partition {} is truncated".format(partition.number))
                os.pwrite(output.fileno(), chunk, data - partition.start_bytes)
                data += len(chunk)
            position = hole


def _next_data(descriptor: int, position: int, end: int) -> tuple[int, int]:
    """Returns the next range of data in [position, end), or (end, end) if only holes are left."""
    try:
        data = os.lseek(descriptor, position, os.SEEK_DATA)
    except OSError as error:
        if error.errno == errno.ENXIO:
            return end, end
        # The file system cannot report holes, so the rest is read as data.
        return position, end
    if data >= end:
        return end, end
    return data, min(os.lseek(descriptor, data, os.SEEK_HOLE), end)


def extract_root_partition(image: str | os.PathLike[str], destination: Path, architecture: str = "amd64") -> Partition:
    """Copies the one populated root partition of a Debian architecture of a disk image to destination.

    Raises:
        AssertionError: If the image has no or several populated root partitions of the architecture.
        ValueError: If the image has no valid GPT or the architecture is not supported.
    """
    root = find_root_partition(image, architecture)
    extract_partition(image, root, destination)
    return root


def _run_debugfs(launcher: str | os.PathLike[str], file_system: Path, request: str) -> tuple[bytes, bytes]:
    """Returns the standard output and error of one read-only debugfs request on an ext4 file system image."""
    environment = {name: os.environ[name] for name in _RUNFILES_VARIABLES if name in os.environ}
    environment["PATH"] = ""
    # The launcher requires a new, empty scratch directory for each run.
    environment["MKOSI_DEBIAN_TOOLS_SCRATCH"] = tempfile.mkdtemp(prefix="debugfs-", dir=os.environ["TEST_TMPDIR"])
    result = subprocess.run(
        [
            launcher,
            "--ro-bind",
            "{}:{}".format(file_system.absolute(), _FILE_SYSTEM),
            "/usr/sbin/debugfs",
            "-R",
            request,
            _FILE_SYSTEM,
        ],
        env=environment,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(
            "debugfs request {!r} failed with {}: {!r}".format(request, result.returncode, result.stderr)
        )
    return result.stdout, result.stderr


def run_debugfs(launcher: str | os.PathLike[str], file_system: Path, request: str) -> str:
    """Returns the output and messages of one read-only debugfs request, such as "stat /etc", on an ext4 image.

    debugfs reports a missing path in its messages and still succeeds.

    Raises:
        AssertionError: If debugfs fails.
    """
    stdout, stderr = _run_debugfs(launcher, file_system, request)
    return (stdout + stderr).decode()


def read_file(launcher: str | os.PathLike[str], file_system: Path, path: str) -> bytes:
    """Returns the content of the file at an absolute path in an ext4 file system image.

    Raises:
        FileNotFoundError: If the path does not exist.
        AssertionError: If debugfs fails.
    """
    stdout, stderr = _run_debugfs(launcher, file_system, "cat " + path)
    if b"File not found" in stderr:
        raise FileNotFoundError(errno.ENOENT, "not in the file system image", path)
    return stdout


def read_os_release(launcher: str | os.PathLike[str], file_system: Path) -> dict[str, str]:
    """Returns the fields of /usr/lib/os-release of an ext4 root file system image, with quotes removed.

    Raises:
        AssertionError: If the image has no ext4 file system or no os-release, as an empty root partition has none.
    """
    try:
        content = read_file(launcher, file_system, "/usr/lib/os-release").decode()
    except FileNotFoundError:
        message = "{} has no /usr/lib/os-release; is the root partition empty?".format(file_system)
        raise AssertionError(message) from None
    fields = dict(line.split("=", 1) for line in content.splitlines() if "=" in line and not line.startswith("#"))
    return {key: value.strip("\"'") for key, value in fields.items()}


def require_populated_root(launcher: str | os.PathLike[str], file_system: Path) -> None:
    """Fails unless a root file system image holds an operating system tree rather than an empty file system.

    An ext4 root needs a /usr/lib/os-release with an ID. The Debian tools launcher runs no EROFS reader, so an EROFS
    root needs more than the one inode of an empty root directory.

    Raises:
        AssertionError: If the image has neither an ext4 nor an EROFS superblock, or holds no tree.
    """
    with file_system.open("rb") as source:
        superblock = source.read(2048)
    if superblock[1080:1082] == _EXT4_MAGIC:
        if not read_os_release(launcher, file_system).get("ID"):
            raise AssertionError("{} has an os-release without ID".format(file_system))
    elif superblock[1024:1028] == _EROFS_MAGIC:
        # struct erofs_super_block: the 64-bit inode count follows magic, checksum, features, block size bits,
        # extension slots and the root inode number.
        inodes = int.from_bytes(superblock[1040:1048], "little")
        if inodes <= 1:
            raise AssertionError("{} is an empty EROFS file system with {} inode".format(file_system, inodes))
    else:
        raise AssertionError("{} has no ext4 or EROFS superblock; is the root partition empty?".format(file_system))
