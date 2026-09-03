"""Boundary tests for embedded Authenticode import."""

import json
import pathlib
import struct
import subprocess
import sys
import unittest


TOOL, DEBIAN_TOOLS = sys.argv[1:3]


def minimal_pe(marker=b"requested UKI"):
    data = bytearray(0x400)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 1, 0, 0, 0, 0xF0, 0x22)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<I", data, optional + 16, 0x1000)
    struct.pack_into("<Q", data, optional + 24, 0x400000)
    struct.pack_into("<II", data, optional + 32, 0x1000, 0x200)
    struct.pack_into("<I", data, optional + 56, 0x2000)
    struct.pack_into("<I", data, optional + 60, 0x200)
    struct.pack_into("<H", data, optional + 68, 10)
    struct.pack_into("<I", data, optional + 108, 16)
    section = optional + 0xF0
    data[section:section + 8] = b".linux\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x200, 0x1000, 0x200, 0x200)
    data[0x200:0x200 + len(marker)] = marker
    return bytes(data)


class SecureBootBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path("secure-boot-boundary-work") / self._testMethodName
        self.work.mkdir(parents=True, exist_ok=True)
        self.unsigned = self.work / "unsigned.efi"
        self.unsigned.write_bytes(minimal_pe())
        self.cert = self.work / "certificate.pem"
        self.signed = self.work / "signed.efi"
        self.run_tool(
            "ephemeral-fixture",
            "--openssl", DEBIAN_TOOLS,
            "--sbsign", DEBIAN_TOOLS,
            "--unsigned-uki", self.unsigned,
            "--certificate", self.cert,
            "--signed-uki", self.signed,
            "--scratch", self.work / "private-scratch",
        )
        self.request = self.work / "request.json"
        self.request_digest = self.work / "request.sha256"
        self.run_tool(
            "request",
            "--openssl", DEBIAN_TOOLS,
            "--unsigned-uki", self.unsigned,
            "--certificate", self.cert,
            "--algorithm", "authenticode-sha256",
            "--output", self.request,
            "--digest-output", self.request_digest,
        )

    def run_tool(self, command, *arguments, check=True):
        result = subprocess.run(
            [sys.executable, TOOL, command, *map(str, arguments)],
            capture_output=True,
            text=True,
        )
        if check and result.returncode:
            self.fail(result.stderr)
        return result

    def verify(self, signed=None, request=None, certificate=None):
        return self.run_tool(
            "verify",
            "--openssl", DEBIAN_TOOLS,
            "--request", request or self.request,
            "--request-digest", self.request_digest,
            "--unsigned-uki", self.unsigned,
            "--signed-uki", signed or self.signed,
            "--certificate", certificate or self.cert,
            "--pkcs7", self.work / "signature.der",
            "--content", self.work / "content.bin",
            "--output", self.work / "verified.efi",
            "--metadata", self.work / "verification.json",
            check=False,
        )

    def test_real_authenticode_signature_and_equivalence(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work / "verified.efi").read_bytes(), self.signed.read_bytes())

    def test_arbitrary_and_tampered_bytes_are_rejected(self):
        arbitrary = self.work / "arbitrary.efi"
        arbitrary.write_bytes(b"detached signatures are insufficient")
        self.assertNotEqual(self.verify(arbitrary).returncode, 0)
        tampered = self.work / "tampered.efi"
        data = bytearray(self.signed.read_bytes())
        data[0x210] ^= 1
        tampered.write_bytes(data)
        self.assertIn("differs", self.verify(tampered).stderr)

    def test_malformed_duplicate_and_trailing_certificate_tables_are_rejected(self):
        original = self.signed.read_bytes()
        _, _, certificate_offset, certificate_size = self._security(original)
        for name, data in {
            "bounds": original[:certificate_offset + certificate_size - 1],
            "trailing": original + b"x",
            "duplicate": original + original[certificate_offset:certificate_offset + certificate_size],
        }.items():
            candidate = bytearray(data)
            if name == "duplicate":
                struct.pack_into("<I", candidate, self._directory_offset(candidate) + 4, certificate_size * 2)
            path = self.work / (name + ".efi")
            path.write_bytes(candidate)
            self.assertNotEqual(self.verify(path).returncode, 0)

    def test_wrong_certificate_algorithm_request_and_different_uki_are_rejected(self):
        other_unsigned = self.work / "other.efi"
        other_unsigned.write_bytes(minimal_pe(b"different valid UKI"))
        other_cert = self.work / "other.pem"
        other_signed = self.work / "other-signed.efi"
        self.run_tool(
            "ephemeral-fixture",
            "--openssl", DEBIAN_TOOLS,
            "--sbsign", DEBIAN_TOOLS,
            "--unsigned-uki", other_unsigned,
            "--certificate", other_cert,
            "--signed-uki", other_signed,
            "--scratch", self.work / "other-private",
        )
        self.assertIn("certificate", self.verify(certificate=other_cert).stderr)
        self.assertNotEqual(self.verify(signed=other_signed).returncode, 0)
        altered = self.work / "altered-request.json"
        document = json.loads(self.request.read_text())
        document["signature_algorithm"] = "authenticode-sha1"
        altered.write_text(json.dumps(document))
        self.assertIn("context or algorithm", self.verify(request=altered).stderr)

    @staticmethod
    def _directory_offset(data):
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        return pe + 24 + 112 + 32

    @classmethod
    def _security(cls, data):
        offset = cls._directory_offset(data)
        return offset, offset + 4, *struct.unpack_from("<II", data, offset)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
