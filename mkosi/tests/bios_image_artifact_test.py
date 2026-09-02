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
# the install-time blocklist is GRUB_BOOT_MACHINE_LIST_SIZE (12) byte entries.
# diskboot.S places firstlist at 0x200 - 12 (0x1f4); additional entries grow
# downward and setup bounds them above the code ending before 0x1b0.
BLOCKLIST_OFFSET = 0x1B0
BLOCKLIST_LAST = 0x1F4
BLOCKLIST_END = 0x200
REQUIRED_MODULES = ("normal", "biosdisk", "part_gpt", "ext2", "linux")
MAX_ROOT_BYTES = 4 * 1024 * 1024 * 1024
ESP = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


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
    differences = [i for i in range(len(reference)) if i not in mutable and actual[i] != reference[i]]
    if differences:
        detail = ", ".join(
            "0x{:x}={:02x}/{:02x}".format(i, actual[i], reference[i])
            for i in differences[:16]
        )
        raise AssertionError("{}: {}".format(diagnostic, detail))


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
        for offset in range(BLOCKLIST_LAST, BLOCKLIST_OFFSET - 1, -12):
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
        # mkimage patches compressed/uncompressed sizes at 0x08/0x0c,
        # Reed-Solomon sizes at 0x10/0x14, and boot device at 0x18. These
        # GRUB 2.12 offsets are declared in include/grub/offsets.h.
        if len(linked) < len(decompressor_reference):
            raise AssertionError("GRUB linked core image is shorter than its decompressor")
        _same_except(
            linked[: len(decompressor_reference)],
            decompressor_reference,
            ((0x08, 0x1C),),
            "GRUB linked core decompressor invariant bytes differ",
        )


def _debugfs(launcher, root, command):
    invocation = getattr(_debugfs, "invocation", 0)
    _debugfs.invocation = invocation + 1
    environment = {n: os.environ[n] for n in ("RUNFILES_DIR", "RUNFILES_MANIFEST_FILE", "RUNFILES_MANIFEST_ONLY") if n in os.environ}
    environment.update({
        "MKOSI_DEBIAN_TOOLS_SCRATCH": os.path.join(os.environ["TEST_TMPDIR"], "bios-debugfs-{}".format(invocation)),
        "PATH": "",
    })
    result = subprocess.run(
        [launcher, "--ro-bind", "{}:/inputs/root.ext4".format(root), "/usr/sbin/debugfs", "-R", command, "/inputs/root.ext4"],
        env=environment, capture_output=True, check=False, text=True,
    )
    if result.returncode:
        raise AssertionError("GRUB root filesystem inspection failed: " + result.stdout + result.stderr)
    return result.stdout + result.stderr


def _mtype(launcher, esp):
    invocation = getattr(_debugfs, "invocation", 0)
    _debugfs.invocation = invocation + 1
    environment = {
        n: os.environ[n]
        for n in ("RUNFILES_DIR", "RUNFILES_MANIFEST_FILE", "RUNFILES_MANIFEST_ONLY")
        if n in os.environ
    }
    environment.update({
        "MKOSI_DEBIAN_TOOLS_SCRATCH": os.path.join(os.environ["TEST_TMPDIR"], "bios-mtype-{}".format(invocation)),
        "PATH": "",
    })
    listing = subprocess.run(
        [launcher, "--ro-bind", "{}:/inputs/esp.fat".format(esp), "/usr/bin/mdir", "-i", "/inputs/esp.fat", "-b", "-/", "::"],
        env=environment, capture_output=True, check=False, text=True,
    )
    configs = [line.strip() for line in listing.stdout.splitlines() if line.strip().lower().endswith("/grub.cfg")]
    if listing.returncode:
        raise AssertionError("GRUB ESP listing failed: " + listing.stdout + listing.stderr)
    if not configs:
        return None
    if len(configs) != 1:
        raise AssertionError("GRUB ESP contains multiple grub.cfg files: " + listing.stdout)
    invocation += 1
    environment["MKOSI_DEBIAN_TOOLS_SCRATCH"] = os.path.join(
        os.environ["TEST_TMPDIR"], "bios-mtype-{}".format(invocation)
    )
    result = subprocess.run(
        [launcher, "--ro-bind", "{}:/inputs/esp.fat".format(esp), "/usr/bin/mtype", "-i", "/inputs/esp.fat", configs[0]],
        env=environment, capture_output=True, check=False, text=True,
    )
    if result.returncode:
        raise AssertionError("GRUB ESP configuration inspection failed: " + result.stdout + result.stderr)
    _mtype.esp = esp
    _mtype.entries = {
        line.strip().removeprefix("::").lower()
        for line in listing.stdout.splitlines()
        if line.strip()
    }
    return result.stdout


def _fat_regular(launcher, esp, path):
    invocation = getattr(_debugfs, "invocation", 0)
    _debugfs.invocation = invocation + 1
    environment = {
        n: os.environ[n]
        for n in ("RUNFILES_DIR", "RUNFILES_MANIFEST_FILE", "RUNFILES_MANIFEST_ONLY")
        if n in os.environ
    }
    environment.update({
        "MKOSI_DEBIAN_TOOLS_SCRATCH": os.path.join(os.environ["TEST_TMPDIR"], "bios-fat-stat-{}".format(invocation)),
        "PATH": "",
    })
    result = subprocess.run(
        [launcher, "--ro-bind", "{}:/inputs/esp.fat".format(esp), "/usr/bin/mdir", "-i", "/inputs/esp.fat", "::" + path],
        env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False, text=True,
    )
    return "regular" if result.returncode == 0 else "missing"


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
                chunk = os.pread(source.fileno(), min(1024 * 1024, hole - position), position)
                if not chunk:
                    raise AssertionError("Linux root partition is truncated")
                output.seek(position - start)
                output.write(chunk)
                position += len(chunk)


def _extract_esp(image, esp, destination):
    if esp["size_bytes"] > 256 * 1024 * 1024:
        raise AssertionError("ESP exceeds inspection resource limit")
    with image.open("rb") as source, destination.open("wb") as output:
        position = esp["start_bytes"]
        remaining = esp["size_bytes"]
        while remaining:
            chunk = os.pread(source.fileno(), min(1024 * 1024, remaining), position)
            if not chunk:
                raise AssertionError("ESP is truncated")
            output.write(chunk)
            position += len(chunk)
            remaining -= len(chunk)


def _stat_type(launcher, root, path):
    output = _debugfs(launcher, root, "stat " + path)
    match = re.search(r"Type:\s+(\w+)", output)
    if not match:
        if "not found" in output.lower():
            return "missing"
        raise AssertionError("cannot parse debugfs stat for {}: {}".format(path, output.strip()))
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
        raise AssertionError("GRUB configuration has no genuine menuentry body: {!r}".format(config[:2048]))
    body = "\n".join(body_lines)
    linux = re.search(r"(?m)^\s*linux\S*\s+(\S+)", body)
    initrd = re.search(r"(?m)^\s*initrd\S*\s+(\S+)", body)
    if not linux or not initrd:
        raise AssertionError("GRUB menuentry is missing linux/initrd commands")
    kernel_path, initrd_path = linux.group(1), initrd.group(1)
    kernel_version = re.fullmatch(r"/(?:boot/)?vmlinuz-(.+)", kernel_path)
    if not kernel_version:
        kernel_version = re.fullmatch(r"/(?:boot/)?[^/]+/([^/]+)/vmlinuz", kernel_path)
    initrd_version = re.fullmatch(r"/(?:boot/)?initrd(?:\.img)?-(.+)", initrd_path)
    if not initrd_version:
        initrd_version = re.fullmatch(r"/(?:boot/)?[^/]+/([^/]+)/kernel-modules\.initrd", initrd_path)
    if not kernel_version or not initrd_version or kernel_version.group(1) != initrd_version.group(1):
        raise AssertionError("GRUB kernel and initrd versions do not match")
    for path in (kernel_path, initrd_path):
        if entries.get(path) != "regular":
            raise AssertionError(
                "GRUB menuentry references missing non-regular file: {} ({})".format(path, entries.get(path))
            )
    referenced = set(REQUIRED_MODULES)
    referenced.update(re.findall(r"(?m)^\s*insmod\s+([A-Za-z0-9_]+)\s*$", body))
    for module in sorted(referenced):
        if modules.get(module) != "regular":
            raise AssertionError(
                "required GRUB i386-pc module is missing: {} ({})".format(module, modules.get(module))
            )


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
    esp = pathlib.Path(os.environ["TEST_TMPDIR"]) / "esp.fat"
    try:
        _extract_root(image, metadata, root)
        config = None
        for index, partition in enumerate(p for p in metadata["partitions"] if p["type_guid"] == ESP):
            candidate = esp.with_name("esp-{}.fat".format(index))
            _extract_esp(image, partition, candidate)
            config = _mtype(launcher, candidate)
            if config is None:
                candidate.unlink(missing_ok=True)
            if config is not None:
                break
        if config is None:
            config = _debugfs(launcher, root, "cat /grub/grub.cfg")
        uncommented = "\n".join(line.split("#", 1)[0] for line in config.splitlines())
        menu_paths = set(re.findall(r"(?m)^\s*(?:linux|linux16|initrd|initrd16)\s+(\S+)", uncommented))
        entries = {
            path: (
                _fat_regular(launcher, _mtype.esp, path)
                if config is not None and hasattr(_mtype, "esp")
                else _stat_type(launcher, root, path if path.startswith("/boot/") else "/boot" + path)
            )
            for path in menu_paths
        }
        names = set(REQUIRED_MODULES)
        names.update(re.findall(r"(?m)^\s*insmod\s+([A-Za-z0-9_]+)\s*$", uncommented))
        modules = {name: _stat_type(launcher, root, "/usr/lib/grub/i386-pc/" + name + ".mod") for name in names}
        validate_boot_files(entries, modules, config)
    finally:
        root.unlink(missing_ok=True)
        esp.unlink(missing_ok=True)
        for candidate in pathlib.Path(os.environ["TEST_TMPDIR"]).glob("esp-*.fat"):
            candidate.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
