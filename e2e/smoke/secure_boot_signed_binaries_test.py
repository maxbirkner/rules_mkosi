"""Checks the verified signed UKI and systemd-boot binary of a release image, imported from an ephemeral signer."""

import hashlib
import json
import struct
import sys
import unittest
from pathlib import Path

_SECURITY_DIRECTORY = 4


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _by_suffix(paths, suffix):
    matches = [Path(path) for path in paths if path.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError("expected one {} in {}".format(suffix, paths))
    return matches[0]


def _certificate_table(data):
    """Returns the offset and size of the PE certificate table."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe + 24
    fixed_size = 112 if struct.unpack_from("<H", data, optional)[0] == 0x20B else 96
    return struct.unpack_from("<II", data, optional + fixed_size + 8 * _SECURITY_DIRECTORY)


class SignedBinary:
    def __init__(self, request_outputs, import_outputs):
        self.request = json.loads(_by_suffix(request_outputs, ".secure-boot-request.json").read_text())
        self.unsigned = _by_suffix(request_outputs, ".efi")
        self.signed = _by_suffix(import_outputs, ".signed.efi")
        self.metadata = json.loads(_by_suffix(import_outputs, ".secure-boot-verification.json").read_text())


class SignedBinariesTest(unittest.TestCase):
    def check(self, binary, esp_path, context):
        self.assertEqual(binary.request["esp_path"], esp_path)
        self.assertEqual(binary.request["context"], context)
        self.assertEqual(binary.request["format_version"], "mkosi-secure-boot-signing-request-v3")
        self.assertEqual(binary.request["unsigned_sha256"], _sha256(binary.unsigned))
        self.assertEqual(binary.metadata["esp_path"], esp_path)
        self.assertEqual(binary.metadata["unsigned_sha256"], _sha256(binary.unsigned))
        self.assertEqual(binary.metadata["signed_sha256"], _sha256(binary.signed))
        self.assertEqual(binary.metadata["certificate_sha256"], binary.request["certificate_sha256"])
        unsigned = binary.unsigned.read_bytes()
        signed = binary.signed.read_bytes()
        self.assertEqual(_certificate_table(unsigned), (0, 0))
        offset, size = _certificate_table(signed)
        self.assertGreaterEqual(offset, len(unsigned))
        self.assertEqual(offset + size, len(signed))

    def test_uki(self):
        self.check(UKI, "", "uefi-secure-boot-uki")

    def test_systemd_boot(self):
        self.check(SYSTEMD_BOOT, "EFI/systemd/systemd-bootx64.efi", "uefi-secure-boot-esp-file")
        self.assertIn(b"systemd-boot", SYSTEMD_BOOT.unsigned.read_bytes())
        self.assertLess(SYSTEMD_BOOT.unsigned.stat().st_size, UKI.unsigned.stat().st_size)


if __name__ == "__main__":
    groups = " ".join(sys.argv[1:]).split(" -- ")
    UKI = SignedBinary(groups[0].split(), groups[1].split())
    SYSTEMD_BOOT = SignedBinary(groups[2].split(), groups[3].split())
    unittest.main(argv=[sys.argv[0]])
