"""Materialize the generated BIOS repart configuration directory."""

import importlib.util
import os
import pathlib
import sys


def _load_sibling(name):
    """Loads the rules_mkosi helper module name.py from this file's directory, independent of sys.path."""
    path = pathlib.Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("rules_mkosi_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gpt = _load_sibling("gpt_partitions")


def main():
    output = pathlib.Path(sys.argv[1])
    output.mkdir(exist_ok=True)
    bios = output / "00-bios-boot.conf"
    bios.write_text(
        "[Partition]\n"
        f"Type={gpt.BIOS_BOOT}\n"
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
        "CopyFiles=/boot:/\n"
        "SizeMinBytes=192M\n"
        "SizeMaxBytes=192M\n",
        encoding="utf-8",
    )
    root = output / "02-root.conf"
    root.write_text(
        "[Partition]\n"
        "Type=root-x86-64\n"
        "Format=ext4\n"
        "CopyFiles=/:/\n"
        "SizeMinBytes=512M\n",
        encoding="utf-8",
    )
    for path in (bios, esp, root):
        os.chmod(path, 0o644)


if __name__ == "__main__":
    main()
