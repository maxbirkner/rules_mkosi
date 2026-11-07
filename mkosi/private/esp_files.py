"""Reads files from the EFI system partition of a release disk image with the pinned mtools."""

import json
import re
import runpy
import shlex
from pathlib import Path

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
gpt = _load_sibling(__file__, "gpt_partitions")
launcher_tool = _load_sibling(__file__, "launcher_tool")

_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_CHUNK = 1 << 20


def validate_esp_path(path):
    """Returns path if it is a relative ESP file path such as EFI/systemd/systemd-bootx64.efi; raises ValueError."""
    components = path.split("/")
    if len(path) > 255 or not all(_COMPONENT.fullmatch(component) for component in components):
        raise ValueError(
            "ESP path {!r} must be a relative path of letters, digits, '.', '_', '+' and '-' components".format(path)
        )
    return path


def esp_extent(partition_metadata):
    """Returns the byte offset and size of the only EFI system partition in the partition metadata file."""
    partitions = json.loads(Path(partition_metadata).read_text(encoding="utf-8"))["partitions"]
    esps = [partition for partition in partitions if partition["type_guid"] == gpt.ESP]
    if len(esps) != 1:
        raise ValueError("image must contain exactly one EFI system partition, found {}".format(len(esps)))
    return esps[0]["start_bytes"], esps[0]["size_bytes"]


def copy_range(source, destination, offset, size, destination_offset=0, sparse=True):
    """Copies size bytes at offset of source to destination_offset of destination.

    With sparse, zero blocks are skipped, which leaves holes in a new destination but keeps old bytes in an existing
    one, so overwriting existing data needs sparse=False.
    """
    with open(source, "rb") as reader, open(destination, "r+b" if Path(destination).exists() else "wb") as writer:
        reader.seek(offset)
        copied = 0
        while copied < size:
            block = reader.read(min(_CHUNK, size - copied))
            if not block:
                raise ValueError("{} ends before byte {}".format(source, offset + size))
            if not sparse or block.count(0) != len(block):
                writer.seek(destination_offset + copied)
                writer.write(block)
            copied += len(block)
        writer.truncate(max(writer.seek(0, 2), destination_offset + size))


def extract_esp(image, partition_metadata, destination):
    """Copies the EFI system partition of image to the file destination and returns its offset in image."""
    offset, size = esp_extent(partition_metadata)
    Path(destination).unlink(missing_ok=True)
    copy_range(image, destination, offset, size)
    return offset


def extract_file(tool, esp_image, esp_path, output):
    """Copies the file at esp_path of the FAT file system esp_image to output."""
    launcher_tool.run_tool(tool, "/usr/bin/mcopy", "-n", "-i", Path(esp_image), "::/" + esp_path, Path(output))


def run_script(tool, scratch, lines, environment):
    """Runs shell lines, with environment exported, in the tools namespace in one call; paths are namespace paths."""
    script = Path(scratch) / "run.sh"
    exports = ["export {}={}".format(name, shlex.quote(value)) for name, value in sorted(environment.items())]
    script.write_text("\n".join(["set -eu", *exports, *lines]) + "\n")
    launcher_tool.run_tool(tool, "/bin/sh", script)


def copy_tree_command(tool, esp_image, tree):
    """Returns the shell line that copies every file and directory of the FAT file system esp_image into tree."""
    return "/bin/mkdir -p {tree} && /usr/bin/mcopy -s -p -m -n -i {image} '::*' {tree}/".format(
        image=shlex.quote(launcher_tool.namespace_path(tool, esp_image)),
        tree=shlex.quote(launcher_tool.namespace_path(tool, tree)),
    )


def tree_files(tree):
    """Returns the ESP paths of the regular files below tree, sorted."""
    root = Path(tree)
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
