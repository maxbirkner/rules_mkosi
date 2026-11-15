"""Proves that an arm64 release image boots through arm64 EFI binaries and has arm64 A/B root slots."""

import json
import pathlib
import struct
import sys

import rules_mkosi_esp_manifest as esp_manifest

from mkosi.tests.runfile_paths import resolve_runfile

_MACHINE_ARM64 = 0xAA64
_ROOT_ARM64 = "b921b045-1df0-41c3-af44-4c6f280d3fae"
_ROOT_ARM64_VERITY = "df3300ce-d69f-4c92-978c-9bfb0f38d820"


def pe_machine(executable: bytes) -> int:
    """Returns the COFF machine type of a PE executable."""
    header = struct.unpack_from("<I", executable, 0x3C)[0]
    assert executable[:2] == b"MZ" and executable[header : header + 4] == b"PE\0\0", "not a PE executable"
    return int(struct.unpack_from("<H", executable, header + 4)[0])


def main() -> None:
    image, partition_metadata, uki, payload = (resolve_runfile(path) for path in sys.argv[1:5])

    esp_paths = {file.path for file in esp_manifest.list_esp_files(image)}
    for path in ("EFI/BOOT/BOOTAA64.EFI", "EFI/systemd/systemd-bootaa64.efi", "EFI/Linux/rules-mkosi-arm64_1.efi"):
        assert path in esp_paths, sorted(esp_paths)
        assert pe_machine(esp_manifest.read_esp_file(image, path)) == _MACHINE_ARM64, path
    assert pe_machine(uki.read_bytes()) == _MACHINE_ARM64

    metadata = json.loads(partition_metadata.read_text())
    assert metadata["architecture"] == "arm64", metadata
    slots = [(partition["label"], partition["type_guid"]) for partition in metadata["partitions"][1:]]
    assert slots == [
        ("rules-mkosi-arm64_1", _ROOT_ARM64),
        ("rules-mkosi-arm64_1_verity", _ROOT_ARM64_VERITY),
        ("_empty", _ROOT_ARM64),
        ("_empty", _ROOT_ARM64_VERITY),
    ], slots

    files = sorted(path.name for path in pathlib.Path(payload).iterdir())
    assert len(files) == 4 and "SHA256SUMS" in files and "rules-mkosi-arm64_1.efi" in files, files


if __name__ == "__main__":
    main()
