"""Materialize the generated BIOS repart configuration directory."""

import os
import pathlib
import runpy
import sys

_load_sibling = runpy.run_path(str(pathlib.Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
gpt = _load_sibling(__file__, "gpt_partitions")

_DEFINITIONS = (
    (
        "00-bios-boot.conf",
        "[Partition]\n"
        f"Type={gpt.BIOS_BOOT}\n"
        "SizeMinBytes=1M\n"
        "SizeMaxBytes=1M\n",
    ),
    # mkosi v27's GRUB BIOS installer also requires an ESP as the location for
    # the generated GRUB configuration, even though firmware never executes it.
    (
        "01-esp.conf",
        "[Partition]\n"
        "Type=esp\n"
        "Format=vfat\n"
        "CopyFiles=/efi:/\n"
        "CopyFiles=/boot:/\n"
        "SizeMinBytes=192M\n"
        "SizeMaxBytes=192M\n",
    ),
    (
        "02-root.conf",
        "[Partition]\n"
        "Type=root-x86-64\n"
        "Format=ext4\n"
        "CopyFiles=/:/\n"
        "SizeMinBytes=512M\n",
    ),
)


def main():
    output = pathlib.Path(sys.argv[1])
    output.mkdir(exist_ok=True)
    paths = []
    for name, content in _DEFINITIONS:
        path = output / name
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    for path in paths:
        os.chmod(path, 0o644)


if __name__ == "__main__":
    main()
