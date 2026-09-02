"""Materialize the generated BIOS repart configuration directory."""

import pathlib
import sys


def main():
    output = pathlib.Path(sys.argv[1])
    output.mkdir()
    (output / "00-bios-boot.conf").write_text(
        "[Partition]\n"
        "Type=21686148-6449-6e6f-744e-656564454649\n"
        "SizeMinBytes=1M\n"
        "SizeMaxBytes=1M\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
