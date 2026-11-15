"""Proves that the Secure Boot signed arm64 image carries signed arm64 boot binaries and keys to enroll."""

import struct
import sys

import rules_mkosi_esp_manifest as esp_manifest

from mkosi.tests.runfile_paths import resolve_runfile

_MACHINE_ARM64 = 0xAA64
_PE32_PLUS = 0x20B
_SECURITY_DIRECTORY = 4


def signed_pe_machine(executable: bytes) -> int:
    """Returns the COFF machine type of a PE executable after checking that it has a certificate table."""
    header = struct.unpack_from("<I", executable, 0x3C)[0]
    assert executable[header : header + 4] == b"PE\0\0", "not a PE executable"
    optional = header + 24
    assert struct.unpack_from("<H", executable, optional)[0] == _PE32_PLUS, "not a PE32+ executable"
    offset, size = struct.unpack_from("<II", executable, optional + 112 + 8 * _SECURITY_DIRECTORY)
    assert offset and size, "unsigned PE executable"
    return int(struct.unpack_from("<H", executable, header + 4)[0])


def main() -> None:
    image = resolve_runfile(sys.argv[1])
    paths = {file.path for file in esp_manifest.list_esp_files(image)}
    for path in ("EFI/systemd/systemd-bootaa64.efi", "EFI/Linux/rules-mkosi-arm64_1.efi"):
        assert signed_pe_machine(esp_manifest.read_esp_file(image, path)) == _MACHINE_ARM64, path
    for key in ("PK", "KEK", "db"):
        assert "loader/keys/auto/{}.auth".format(key) in paths, sorted(paths)


if __name__ == "__main__":
    main()
