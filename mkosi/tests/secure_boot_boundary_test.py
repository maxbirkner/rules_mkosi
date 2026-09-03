"""Boundary tests for embedded Authenticode import."""

import json
import importlib.util
import hashlib
import pathlib
import struct
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


TOOL, DEBIAN_TOOLS = sys.argv[1:3]
SPEC = importlib.util.spec_from_file_location("secure_boot", TOOL)
SECURE_BOOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SECURE_BOOT)


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
        self.other_unsigned = self.work / "same-layout-other.efi"
        self.other_unsigned.write_bytes(minimal_pe(b"other payload"))
        self.other_signed = self.work / "same-layout-other-signed.efi"
        self.run_tool(
            "ephemeral-fixture",
            "--openssl", DEBIAN_TOOLS,
            "--sbsign", DEBIAN_TOOLS,
            "--unsigned-uki", self.unsigned,
            "--certificate", self.cert,
            "--signed-uki", self.signed,
            "--scratch", self.work / "private-scratch",
            "--other-unsigned", self.other_unsigned,
            "--other-signed", self.other_signed,
        )
        self.request = self.work / "request.json"
        self.request_digest = self.work / "request.sha256"
        self.run_tool(
            "request",
            "--openssl", DEBIAN_TOOLS,
            "--unsigned-uki", self.unsigned,
            "--certificate", self.cert,
            "--certificate-output", self.work / "normalized-certificate.der",
            "--algorithm", "authenticode-sha256",
            "--output", self.request,
            "--digest-output", self.request_digest,
        )
        self.normalized_certificate = self.work / "normalized-certificate.der"

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
            "--expected-pem", self.work / "expected-certificate.pem",
            "--pkcs7", self.work / "signature.der",
            "--content", self.work / "content.bin",
            "--verified-signer", self.work / "verified-signer.pem",
            "--output", self.work / "verified.efi",
            "--metadata", self.work / "verification.json",
            check=False,
        )

    def test_real_authenticode_signature_and_equivalence(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work / "verified.efi").read_bytes(), self.signed.read_bytes())

    def test_request_emits_canonical_der_certificate_and_matching_fingerprint(self):
        certificate = self.normalized_certificate.read_bytes()
        self.assertTrue(certificate.startswith(b"\x30"))
        self.assertNotIn(b"-----BEGIN CERTIFICATE-----", certificate)
        self.assertEqual(
            json.loads(self.request.read_text())["certificate_sha256"],
            hashlib.sha256(certificate).hexdigest(),
        )

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

    def test_request_rejects_malformed_optional_headers_and_directories(self):
        for name, mutate in {
            "zero-directories": lambda data: struct.pack_into("<I", data, 0x98 + 108, 0),
            "four-directories": lambda data: struct.pack_into("<I", data, 0x98 + 108, 4),
            "truncated-optional": lambda data: struct.pack_into("<H", data, 0x80 + 20, 112),
            "bad-headers": lambda data: struct.pack_into("<I", data, 0x98 + 60, 0x180),
        }.items():
            candidate = bytearray(minimal_pe())
            mutate(candidate)
            path = self.work / (name + ".efi")
            path.write_bytes(candidate)
            result = self.run_tool(
                "request",
                "--openssl", DEBIAN_TOOLS,
                "--unsigned-uki", path,
                "--certificate", self.cert,
                "--certificate-output", self.work / (name + ".pem.normalized"),
                "--algorithm", "authenticode-sha256",
                "--output", self.work / (name + ".json"),
                "--digest-output", self.work / (name + ".sha256"),
                check=False,
            )
            self.assertNotEqual(result.returncode, 0, name)

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
        self.assertIn("request digest", self.verify(request=altered).stderr)

    def test_certificate_bundles_duplicates_reversal_and_trailing_data_are_rejected(self):
        other_cert = self.work / "bundle-other.pem"
        self.run_tool(
            "ephemeral-fixture",
            "--openssl", DEBIAN_TOOLS,
            "--sbsign", DEBIAN_TOOLS,
            "--unsigned-uki", self.other_unsigned,
            "--certificate", other_cert,
            "--signed-uki", self.work / "bundle-other-signed.efi",
            "--scratch", self.work / "bundle-other-private",
        )
        first = self.cert.read_bytes()
        second = other_cert.read_bytes()
        for name, certificate in {
            "bundle": first + second,
            "reversed": second + first,
            "duplicate": first + first,
            "trailing": first + b"not whitespace",
        }.items():
            path = self.work / (name + ".pem")
            path.write_bytes(certificate)
            result = self.run_tool(
                "request",
                "--openssl", DEBIAN_TOOLS,
                "--unsigned-uki", self.unsigned,
                "--certificate", path,
                "--certificate-output", self.work / (name + ".pem.normalized"),
                "--algorithm", "authenticode-sha256",
                "--output", self.work / (name + ".json"),
                "--digest-output", self.work / (name + ".sha256"),
                check=False,
            )
            self.assertIn("certificate", result.stderr)

    def test_request_requires_openssl_validated_x509_and_accepts_der(self):
        for name, value in {
            "empty-sequence": b"\x30\x00",
            "x509-shaped-malformed": b"\x30\x03\x02\x01\x00",
        }.items():
            certificate = self.work / (name + ".der")
            certificate.write_bytes(value)
            result = self.run_tool(
                "request",
                "--openssl", DEBIAN_TOOLS,
                "--unsigned-uki", self.unsigned,
                "--certificate", certificate,
                "--certificate-output", self.work / (name + ".normalized.der"),
                "--algorithm", "authenticode-sha256",
                "--output", self.work / (name + ".json"),
                "--digest-output", self.work / (name + ".sha256"),
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid X.509 certificate", result.stderr)
        result = self.run_tool(
            "request",
            "--openssl", DEBIAN_TOOLS,
            "--unsigned-uki", self.unsigned,
            "--certificate", self.work / "normalized-certificate.der",
            "--certificate-output", self.work / "der-positive.der",
            "--algorithm", "authenticode-sha256",
            "--output", self.work / "der-positive.json",
            "--digest-output", self.work / "der-positive.sha256",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_canonical_certificate_invokes_declared_x509_launcher(self):
        calls = []

        def fake_run(tool, *arguments, **kwargs):
            calls.append((tool, arguments, kwargs))
            return SimpleNamespace(stdout=b"\x30\x00")

        with (
            mock.patch.object(SECURE_BOOT, "run_tool", side_effect=fake_run),
            mock.patch.object(SECURE_BOOT, "isolated_certificate_der", return_value=b"\x30\x00"),
        ):
            self.assertEqual(SECURE_BOOT.canonical_certificate("declared-launcher", b"\x30\x00"), b"\x30\x00")
        self.assertEqual(calls[0][0], "declared-launcher")
        self.assertEqual(calls[0][1][:4], ("/usr/bin/openssl", "x509", "-inform", "DER"))
        self.assertTrue(calls[0][2]["capture"])

    def test_der_rejects_noncanonical_lengths_and_oids_with_bounds(self):
        canonical, _ = SECURE_BOOT.der_read(b"\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x07\x02")
        self.assertEqual(SECURE_BOOT.der_oid(canonical), "1.2.840.113549.1.7.2")
        for encoded in [
            b"\x04\x81\x01x",
            b"\x04\x80",
            b"\x04\x82\x00\x80" + b"x" * 128,
            b"\x04\x85\x01\x00\x00\x00\x00",
        ]:
            with self.assertRaises(ValueError):
                SECURE_BOOT.der_read(encoded)
        for encoded in [
            b"\x06\x02\x80\x01",
            b"\x06\x01\x80",
            b"\x06\x03\x2a\x80\x00",
            b"\x06\x41" + b"\x01" * 65,
            b"\x06\x82\x01\x01" + b"\x01" * 257,
        ]:
            with self.assertRaises(ValueError):
                item, _ = SECURE_BOOT.der_read(encoded)
                SECURE_BOOT.der_oid(item)

    def test_transplanted_trusted_certificate_table_is_rejected(self):
        original = bytearray(self.signed.read_bytes())
        other = self.other_signed.read_bytes()
        _, _, source_offset, source_size = self._security(other)
        _, _, target_offset, target_size = self._security(original)
        self.assertEqual((source_offset, source_size), (target_offset, target_size))
        original[target_offset:target_offset + target_size] = other[source_offset:source_offset + source_size]
        transplanted = self.work / "transplanted.efi"
        transplanted.write_bytes(original)
        self.assertNotEqual(self.verify(transplanted).returncode, 0)

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
