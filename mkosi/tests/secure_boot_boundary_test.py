"""Boundary tests for the offline Secure Boot exchange."""

import json
import pathlib
import subprocess
import sys
import unittest


TOOL, OPENSSL = sys.argv[1:3]


class SecureBootBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path("secure-boot-boundary-work")
        self.work.mkdir(exist_ok=True)
        self.unsigned = self.work / "unsigned.efi"
        self.signed = self.work / "signed.efi"
        self.unsigned.write_bytes(b"unsigned UKI")
        self.signed.write_bytes(b"externally signed UKI")
        self.key = self.work / "key.pem"
        self.cert = self.work / "cert.pem"
        self.run_tool("test-key", "--private-key", self.key, "--certificate", self.cert)
        self.request = self.work / "request.json"
        self.run_tool(
            "request",
            "--unsigned-uki",
            self.unsigned,
            "--certificate",
            self.cert,
            "--output",
            self.request,
        )
        self.response = self.work / "response.json"
        self.signature = self.work / "response.sig"
        self.run_tool(
            "test-response",
            "--request",
            self.request,
            "--signed-uki",
            self.signed,
            "--private-key",
            self.key,
            "--output",
            self.response,
            "--signature",
            self.signature,
        )

    def run_tool(self, command, *arguments, check=True):
        result = subprocess.run(
            [sys.executable, TOOL, command, "--openssl", OPENSSL, *map(str, arguments)],
            capture_output=True,
            text=True,
        )
        if check and result.returncode:
            self.fail(result.stderr)
        return result

    def verify(self, certificate=None):
        return self.run_tool(
            "verify",
            "--request",
            self.request,
            "--response",
            self.response,
            "--signed-uki",
            self.signed,
            "--signature",
            self.signature,
            "--certificate",
            certificate or self.cert,
            "--public-key",
            self.work / "public.pem",
            "--output",
            self.work / "assembled.efi",
            "--metadata",
            self.work / "verification.json",
            check=False,
        )

    def test_valid_response_is_assembled(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work / "assembled.efi").read_bytes(), self.signed.read_bytes())
        metadata = json.loads((self.work / "verification.json").read_text())
        self.assertEqual(metadata["verification"], "openssl-dgst-sha256")

    def test_tampered_signed_uki_is_rejected(self):
        self.signed.write_bytes(b"tampered")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not bind", result.stderr)

    def test_wrong_certificate_is_rejected(self):
        wrong_key = self.work / "wrong-key.pem"
        wrong_cert = self.work / "wrong-cert.pem"
        self.run_tool("test-key", "--private-key", wrong_key, "--certificate", wrong_cert)
        result = self.verify(wrong_cert)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("certificate does not match", result.stderr)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
