"""Materialize the generated BIOS repart configuration directory."""

import os
import pathlib
import sys


def main():
    output = pathlib.Path(sys.argv[1])
    output.mkdir(exist_ok=True)
    bios = output / "00-bios-boot.conf"
    bios.write_text(
        "[Partition]\n"
        "Type=21686148-6449-6e6f-744e-656564454649\n"
        "SizeMinBytes=1M\n"
        "SizeMaxBytes=1M\n",
        encoding="utf-8",
    )
    # mkosi v27's GRUB BIOS installer also requires an ESP as the location for
    # the generated GRUB configuration, even though firmware never executes it.
    esp = output / "01-esp.conf"
    esp.write_text(
        "[Partition]\n"
        "Type=esp\n"
        "Format=vfat\n"
        "CopyFiles=/efi:/\n"
        "SizeMinBytes=64M\n"
        "SizeMaxBytes=64M\n",
        encoding="utf-8",
    )
    root = output / "02-root.conf"
    root.write_text(
        "[Partition]\n"
        "Type=root-x86-64\n"
        "Format=ext4\n"
        "SizeMinBytes=256M\n",
        encoding="utf-8",
    )
    for path in (bios, esp, root):
        os.chmod(path, 0o644)


if __name__ == "__main__":
    main()
