"""Validate rules_mkosi's installed GRUB BIOS artifact semantics."""

import os
import errno
import pathlib
import re
import struct
import subprocess
import sys
import tarfile

from mkosi.private import partition_metadata
from python.runfiles import runfiles

SECTOR = 512
# grub-core/boot/i386/pc/boot.S and include/grub/i386/pc/boot.h (GRUB 2.12):
# installation preserves the BPB at [0x03,0x5a), patches the 64-bit kernel
# sector at 0x5c, boot drive at 0x64, and drive-check instruction at 0x66.
BOOT_PATCHES = ((0x03, 0x5A), (0x5C, 0x65), (0x66, 0x68))
# grub-core/boot/i386/pc/diskboot.S and include/grub/i386/pc/kernel.h:
# the install-time blocklist is GRUB_BOOT_MACHINE_LIST_SIZE (12) byte entries,
# beginning at GRUB_BOOT_MACHINE_LIST_OFFSET (0x1b0), through offset 0x1fc.
BLOCKLIST_OFFSET = 0x1B0
BLOCKLIST_END = 0x1FC
REQUIRED_MODULES = ("normal", "biosdisk", "part_gpt", "ext2", "linux")
MAX_ROOT_BYTES = 4 * 1024 * 1024 * 1024


def _runfile(path):
    if path.startswith("../"):
        path = path[3:]
    elif not path.startswith("external/"):
        path = os.path.join(os.environ["TEST_WORKSPACE"], path)
    return pathlib.Path(runfiles.Create().Rlocation(path))


def _reference(archive, name, size=None):
    with tarfile.open(archive, "r:") as source:
        member = source.getmember("./usr/lib/grub/i386-pc/" + name)
        if not member.isfile() or (size is not None and member.size != size):
            raise AssertionError("pinned grub-pc-bin reference is malformed: " + name)
        return source.extractfile(member).read()


def _same_except(actual, reference, patches, diagnostic):
    mutable = set()
    for start, end in patches:
        mutable.update(range(start, end))
    if any(actual[i] != reference[i] for i in range(len(reference)) if i not in mutable):
        raise AssertionError(diagnostic)


def validate_boot_regions(image, metadata, boot_reference, diskboot_reference, decompressor_reference):
    bios = [p for p in metadata["partitions"] if p["type_guid"] == partition_metadata.BIOS_BOOT]
    if len(bios) != 1:
        raise AssertionError("unique GPT BIOS boot partition is missing")
    partition = bios[0]
    start, size = partition["start_bytes"], partition["size_bytes"]
    if start % partition_metadata.ALIGNMENT or size < partition_metadata.ALIGNMENT:
        raise AssertionError("GPT BIOS boot partition has invalid alignment or size")
    if start % SECTOR or size % SECTOR:
        raise AssertionError("GPT BIOS boot partition is not sector aligned")

    with image.open("rb") as source:
        mbr = source.read(SECTOR)
        if len(mbr) != SECTOR or mbr[510:512] != b"\x55\xaa":
            raise AssertionError("BIOS MBR signature is missing")
        _same_except(mbr, boot_reference, BOOT_PATCHES + ((0x1B8, SECTOR),), "GRUB MBR invariant bytes differ from pinned boot.img")
        source.seek(start)
        diskboot = source.read(SECTOR)
        if len(diskboot) != SECTOR:
            raise AssertionError("GRUB diskboot sector is truncated")
        _same_except(diskboot, diskboot_reference, ((BLOCKLIST_OFFSET, BLOCKLIST_END),), "GRUB diskboot invariant bytes differ from pinned diskboot.img")

        linked = bytearray()
        saw_terminator = False
        for offset in range(BLOCKLIST_OFFSET, BLOCKLIST_END, 12):
            sector, count, segment = struct.unpack_from("<QHH", diskboot, offset)
            if count == 0:
                saw_terminator = True
                break
            byte_start, byte_count = sector * SECTOR, count * SECTOR
            if sector > (sys.maxsize // SECTOR) or count > (size // SECTOR):
                raise AssertionError("GRUB diskboot blocklist arithmetic is invalid")
            if byte_start < start or byte_start + byte_count > start + size:
                raise AssertionError("GRUB diskboot blocklist leaves BIOS boot partition")
            if segment < 0x800 or segment + count * 0x20 > 0xA000:
                raise AssertionError("GRUB diskboot blocklist load segment is invalid")
            source.seek(byte_start)
            data = source.read(byte_count)
            if len(data) != byte_count:
                raise AssertionError("GRUB linked core image is truncated")
            linked.extend(data)
        if not saw_terminator or not linked:
            raise AssertionError("GRUB diskboot blocklist is empty or unterminated")
        # grub-core/boot/i386/pc/startup_raw.S and include/grub/offsets.h:
        # mkimage patches the decompressor's compressed/uncompressed sizes in
        # its 16-byte header; the remaining lzma_decompress.img is invariant.
        if len(linked) < len(decompressor_reference):
            raise AssertionError("GRUB linked core image is shorter than its decompressor")
        _same_except(
            linked[: len(decompressor_reference)],
            decompressor_reference,
            ((0, 16),),
            "GRUB linked core decompressor invariant bytes differ",
        )


def _debugfs(launcher, root, command):
    environment = {n: os.environ[n] for n in ("RUNFILES_DIR", "RUNFILES_MANIFEST_FILE", "RUNFILES_MANIFEST_ONLY") if n in os.environ}
    environment.update({"MKOSI_DEBIAN_TOOLS_SCRATCH": os.path.join(os.environ["TEST_TMPDIR"], "bios-debugfs"), "PATH": ""})
    result = subprocess.run(
        [launcher, "--ro-bind", "{}:/inputs/root.ext4".format(root), "/usr/sbin/debugfs", "-R", command, "/inputs/root.ext4"],
        env=environment, capture_output=True, check=False, text=True,
    )
    if result.returncode:
        raise AssertionError("GRUB root filesystem inspection failed: " + result.stdout + result.stderr)
    return result.stdout + result.stderr


def _extract_root(image, metadata, destination):
    root = next(p for p in metadata["partitions"] if p["type_guid"] == partition_metadata.ROOT_X86_64)
    start, size = root["start_bytes"], root["size_bytes"]
    if size <= 0 or size > MAX_ROOT_BYTES or start < 0 or start > sys.maxsize - size:
        raise AssertionError("Linux root partition exceeds inspection resource limits")
    with image.open("rb") as source, destination.open("wb") as output:
        output.truncate(size)
        position = start
        sparse = hasattr(os, "SEEK_DATA") and hasattr(os, "SEEK_HOLE")
        while position < start + size:
            if sparse:
                try:
                    data = os.lseek(source.fileno(), position, os.SEEK_DATA)
                except OSError as error:
                    if error.errno == errno.ENXIO:
                        break
                    sparse = False
                    position = start
                    output.seek(0)
                    continue
                if data >= start + size:
                    break
                hole = min(os.lseek(source.fileno(), data, os.SEEK_HOLE), start + size)
                position = data
            else:
                hole = start + size
            while position < hole:
                chunk = source.read(min(1024 * 1024, hole - position))
                if not chunk:
                    raise AssertionError("Linux root partition is truncated")
                output.seek(position - start)
                output.write(chunk)
                position += len(chunk)


def _stat_type(launcher, root, path):
    output = _debugfs(launcher, root, "stat " + path)
    match = re.search(r"Type:\s+(\w+)", output)
    if not match:
        raise AssertionError("cannot parse debugfs stat for " + path)
    return match.group(1)


def validate_boot_files(entries, modules, config):
    body_lines = []
    depth = 0
    found = False
    for raw_line in config.splitlines():
        line = raw_line.split("#", 1)[0]
        if not found:
            if not re.match(r"^\s*menuentry(?:\s+[^{]+)?\s*\{", line):
                continue
            found = True
        depth += line.count("{") - line.count("}")
        body_lines.append(line)
        if depth == 0:
            break
    if not found or depth != 0:
        raise AssertionError("GRUB configuration has no genuine menuentry body")
    body = "\n".join(body_lines)
    linux = re.search(r"(?m)^\s*linux\S*\s+(\S+)", body)
    initrd = re.search(r"(?m)^\s*initrd\S*\s+(\S+)", body)
    if not linux or not initrd:
        raise AssertionError("GRUB menuentry is missing linux/initrd commands")
    kernel_path, initrd_path = linux.group(1), initrd.group(1)
    kernel_version = re.fullmatch(r"/boot/vmlinuz-(.+)", kernel_path)
    initrd_version = re.fullmatch(r"/boot/initrd\.img-(.+)", initrd_path)
    if not kernel_version or not initrd_version or kernel_version.group(1) != initrd_version.group(1):
        raise AssertionError("GRUB kernel and initrd versions do not match")
    for path in (kernel_path, initrd_path):
        if entries.get(path) != "regular":
            raise AssertionError("GRUB menuentry references missing non-regular file: " + path)
    referenced = set(REQUIRED_MODULES)
    referenced.update(re.findall(r"(?m)^\s*insmod\s+([A-Za-z0-9_]+)\s*$", body))
    for module in sorted(referenced):
        if modules.get(module) != "regular":
            raise AssertionError("required GRUB i386-pc module is missing: " + module)


def main():
    image, launcher, archive = map(_runfile, sys.argv[1:4])
    metadata = partition_metadata.project_image(image, "bios")
    validate_boot_regions(
        image,
        metadata,
        _reference(archive, "boot.img", SECTOR),
        _reference(archive, "diskboot.img", SECTOR),
        _reference(archive, "lzma_decompress.img"),
    )
    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "root.ext4"
    try:
        _extract_root(image, metadata, root)
        config = _debugfs(launcher, root, "cat /boot/grub/grub.cfg")
        uncommented = "\n".join(line.split("#", 1)[0] for line in config.splitlines())
        menu_paths = set(re.findall(r"(?m)^\s*(?:linux|linux16|initrd|initrd16)\s+(\S+)", uncommented))
        entries = {path: _stat_type(launcher, root, path) for path in menu_paths}
        names = set(REQUIRED_MODULES)
        names.update(re.findall(r"(?m)^\s*insmod\s+([A-Za-z0-9_]+)\s*$", uncommented))
        modules = {name: _stat_type(launcher, root, "/usr/lib/grub/i386-pc/" + name + ".mod") for name in names}
        validate_boot_files(entries, modules, config)
    finally:
        root.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
