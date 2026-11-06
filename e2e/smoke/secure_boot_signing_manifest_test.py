"""Checks that a consumer's signing manifest names each request's files and that the reference signer validates them."""

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


def _split_arguments(arguments):
    """Returns the signer, the manifest rule's outputs and the test signer's outputs."""
    separator = arguments.index("--")
    return arguments[0], arguments[1:separator], arguments[separator + 1 :]


SIGNER, MANIFEST_OUTPUTS, FIXTURE_OUTPUTS = _split_arguments(sys.argv[1:])
MANIFEST = Path(next(path for path in MANIFEST_OUTPUTS if path.endswith(".secure-boot-signing-manifest.json")))
CERTIFICATE = Path(next(path for path in FIXTURE_OUTPUTS if path.endswith(".certificate.pem")))


def _runfile(path):
    """Returns the runfile of the consumer's file at an execution-root-relative path such as bazel-out/<cfg>/bin/x."""
    parts = Path(path).parts
    if parts[0] != "bazel-out" or parts[2] != "bin":
        raise AssertionError("{} is not a generated file of the consumer".format(path))
    return Path(*parts[3:])


class SigningManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text())

    def test_entries_name_each_request_with_its_binary_and_certificate(self):
        self.assertEqual("mkosi-secure-boot-signing-manifest-v1", self.manifest["format_version"])
        entries = self.manifest["requests"]
        self.assertEqual(["systemd-bootx64.efi", "uki.efi"], [entry["signed_name"] for entry in entries])
        self.assertEqual(["EFI/systemd/systemd-bootx64.efi", ""], [entry["esp_path"] for entry in entries])
        for entry in entries:
            request = json.loads(_runfile(entry["request"]).read_text())
            self.assertEqual((request["esp_path"], request["context"]), (entry["esp_path"], entry["context"]))
            unsigned = _runfile(entry["unsigned_binary"]).read_bytes()
            self.assertEqual(request["unsigned_sha256"], hashlib.sha256(unsigned).hexdigest())
            certificate = _runfile(entry["certificate"]).read_bytes()
            self.assertEqual(request["certificate_sha256"], hashlib.sha256(certificate).hexdigest())

    def test_reference_signer_validates_the_manifest_against_the_certificate(self):
        # The manifest's paths are relative to the execution root; map each bazel-out/<cfg>/bin to the runfiles.
        execroot = Path("signing-manifest-execroot").absolute()
        for entry in self.manifest["requests"]:
            configuration = execroot / "bazel-out" / Path(entry["request"]).parts[1]
            configuration.mkdir(parents=True, exist_ok=True)
            if not (configuration / "bin").exists():
                (configuration / "bin").symlink_to(Path.cwd())
        result = subprocess.run(
            [SIGNER, "--validate-only", "--manifest", MANIFEST, "--certificate", CERTIFICATE, "--execroot", execroot],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(2, len([line for line in result.stdout.splitlines() if line.startswith("valid: ")]))


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
