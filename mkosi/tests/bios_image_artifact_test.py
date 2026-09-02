"""Validate rules_mkosi's installed GRUB BIOS artifact semantics."""

import os
import pathlib
import subprocess
import sys

from mkosi.private import partition_metadata
from python.runfiles import runfiles


def _runfile(path):
    if path.startswith("../"):
        path = path[3:]
    elif not path.startswith("external/"):
        path = os.path.join(os.environ["TEST_WORKSPACE"], path)
    return pathlib.Path(runfiles.Create().Rlocation(path))


def validate_boot_regions(image, metadata):
    with image.open("rb") as source:
        mbr = source.read(512)
        if len(mbr) != 512 or mbr[510:512] != b"\x55\xaa":
            raise AssertionError("BIOS MBR signature is missing")
        bootstrap = mbr[:440]
        if not any(bootstrap) or len(set(bootstrap)) < 8:
            raise AssertionError("GRUB MBR bootstrap code is empty or corrupt")
        bios = [p for p in metadata["partitions"] if p["type_guid"] == partition_metadata.BIOS_BOOT]
        if len(bios) != 1:
            raise AssertionError("unique GPT BIOS boot partition is missing")
        partition = bios[0]
        if partition["start_bytes"] % partition_metadata.ALIGNMENT:
            raise AssertionError("GPT BIOS boot partition is not 1 MiB aligned")
        if partition["size_bytes"] < partition_metadata.ALIGNMENT:
            raise AssertionError("GPT BIOS boot partition is smaller than 1 MiB")
        source.seek(partition["start_bytes"])
        core = source.read(partition["size_bytes"])
    if not core.startswith(b"\x52\x56\xbe\x1b\x7c"):
        raise AssertionError("GRUB core image diskboot signature is missing or corrupt")
    if len(set(core[: min(len(core), 65536)])) < 32:
        raise AssertionError("GRUB core image content is empty or implausible")


def _debugfs(launcher, root, command):
    environment = {
        name: os.environ[name]
        for name in ("RUNFILES_DIR", "RUNFILES_MANIFEST_FILE", "RUNFILES_MANIFEST_ONLY")
        if name in os.environ
    }
    environment.update({"MKOSI_DEBIAN_TOOLS_SCRATCH": os.path.join(os.environ["TEST_TMPDIR"], "bios-debugfs"), "PATH": ""})
    result = subprocess.run(
        [launcher, "--ro-bind", "{}:/inputs/root.ext4".format(root), "/usr/sbin/debugfs", "-R", command, "/inputs/root.ext4"],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode:
        raise AssertionError("GRUB root filesystem inspection failed: " + result.stdout + result.stderr)
    return result.stdout + result.stderr


def _extract_root(image, metadata, destination):
    root = next(p for p in metadata["partitions"] if p["type_guid"] == partition_metadata.ROOT_X86_64)
    with image.open("rb") as source, destination.open("wb") as output:
        source.seek(root["start_bytes"])
        remaining = root["size_bytes"]
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise AssertionError("Linux root partition is truncated")
            output.write(chunk)
            remaining -= len(chunk)

def validate_boot_files(boot, modules, config):
    if "/vmlinuz-" not in boot or "/initrd.img-" not in boot:
        raise AssertionError("BIOS image is missing a kernel or matching initrd")
    if "/normal.mod" not in modules or "/linux.mod" not in modules:
        raise AssertionError("BIOS image is missing GRUB i386-pc modules")
    if "menuentry" not in config or "linux" not in config or "initrd" not in config:
        raise AssertionError("BIOS image GRUB configuration has no viable kernel menu entry")


def main():
    image = _runfile(sys.argv[1])
    launcher = _runfile(sys.argv[2])
    metadata = partition_metadata.project_image(image, "bios")
    validate_boot_regions(image, metadata)
    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "root.ext4"
    _extract_root(image, metadata, root)
    boot = _debugfs(launcher, root, "ls -p /boot")
    modules = _debugfs(launcher, root, "ls -p /usr/lib/grub/i386-pc")
    config = _debugfs(launcher, root, "cat /boot/grub/grub.cfg")
    validate_boot_files(boot, modules, config)


if __name__ == "__main__":
    main()
