#!/usr/bin/python3
"""Reference external signer for the requests of a secure_boot_signing_manifest.

Run it outside Bazel actions, with ``bazel run @rules_mkosi//mkosi:secure_boot_signer -- ...``. It validates every
request of the manifest against the binary, the certificate and the key file it is given before signing any of them,
signs each binary with the pinned systemd-sbsign of the Debian tools or a host signing tool, checks the signature
without external tools, and writes the signed binaries under their manifest names. The private key is read in place by
the signing tool; it is never copied or printed.

With --signing-time, or SOURCE_DATE_EPOCH, the signing tool runs with its clock stopped at that time by libfaketime,
so that the signingTime attribute of every signature, and therefore every signed binary, is deterministic.
"""

import argparse
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
secure_boot = _load_sibling(__file__, "secure_boot")
file_hashing = _load_sibling(__file__, "file_hashing")

MANIFEST_FORMAT = "mkosi-secure-boot-signing-manifest-v1"
_ENTRY_FIELDS = {
    "certificate",
    "context",
    "esp_path",
    "label",
    "request",
    "request_digest",
    "signed_name",
    "unsigned_binary",
}
_SIGNED_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_PEM_CERTIFICATE = re.compile(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL)
_OID_RSA_ENCRYPTION = "1.2.840.113549.1.1.1"
_OID_CONTENT_TYPE = "1.2.840.113549.1.9.3"
_OID_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
_OID_SIGNING_TIME = "1.2.840.113549.1.9.5"
# 9999-12-31 23:59:59 UTC, the last second that a GeneralizedTime can hold.
_MAX_SIGNING_TIME = 253402300799
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


class Request(NamedTuple):
    """A validated manifest entry and the bytes of its unsigned binary."""

    label: str
    signed_name: str
    unsigned_data: bytes


def load_json(path):
    """Returns the JSON document at path; raises ValueError on duplicate object keys."""

    def reject_duplicates(pairs):
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("{} has duplicate JSON keys".format(path))
        return dict(pairs)

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)


def load_manifest(path):
    """Returns the entries of a signing manifest after checking its schema and signed file names."""
    manifest = load_json(path)
    if not isinstance(manifest, dict) or manifest.get("format_version") != MANIFEST_FORMAT:
        raise ValueError("{} is not a {} signing manifest".format(path, MANIFEST_FORMAT))
    entries = manifest.get("requests")
    if set(manifest) != {"format_version", "requests"} or not isinstance(entries, list) or not entries:
        raise ValueError("signing manifest must hold exactly format_version and a nonempty requests array")
    names = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
            raise ValueError("signing manifest entries must have exactly the fields {}".format(sorted(_ENTRY_FIELDS)))
        if not all(isinstance(value, str) for value in entry.values()):
            raise ValueError("signing manifest fields of {} must be strings".format(entry["label"]))
        if not _SIGNED_NAME.fullmatch(entry["signed_name"]) or entry["signed_name"] in names:
            raise ValueError("invalid or duplicate signed file name {!r}".format(entry["signed_name"]))
        names.add(entry["signed_name"])
    return entries


def find_execroot(manifest):
    """Returns the execution root that holds manifest: the parent of bazel-out in its real path."""
    for parent in Path(manifest).resolve().parents:
        if parent.name == "bazel-out":
            return parent.parent
    raise ValueError("{} is not below bazel-out; pass --execroot".format(manifest))


def resolve_path(execroot, path):
    """Returns the file at the execution-root-relative path of a manifest entry."""
    if not path or Path(path).is_absolute():
        raise ValueError("manifest path {!r} must be relative to the execution root".format(path))
    return execroot / path


def validate_entry(execroot, entry, certificate):
    """Returns the Request of a manifest entry after checking it against its files and the expected certificate."""
    label = entry["label"]
    request = load_json(resolve_path(execroot, entry["request"]))
    recorded_digest = resolve_path(execroot, entry["request_digest"]).read_text(encoding="utf-8").strip()
    secure_boot.validate_request(request, recorded_digest)
    if (request["esp_path"], request["context"]) != (entry["esp_path"], entry["context"]):
        raise ValueError("{}: request does not match the esp_path and context of the manifest".format(label))
    unsigned_data = resolve_path(execroot, entry["unsigned_binary"]).read_bytes()
    if hashlib.sha256(unsigned_data).hexdigest() != request["unsigned_sha256"]:
        raise ValueError("{}: unsigned binary does not match its request".format(label))
    secure_boot.parse_pe(unsigned_data, False)
    requested = secure_boot.certificate_der(resolve_path(execroot, entry["certificate"]))
    if hashlib.sha256(requested).hexdigest() != request["certificate_sha256"]:
        raise ValueError("{}: request certificate does not match certificate_sha256".format(label))
    if requested != certificate:
        raise ValueError(
            "{}: --certificate (SHA-256 {}) is not the requested certificate (SHA-256 {})".format(
                label, hashlib.sha256(certificate).hexdigest(), request["certificate_sha256"]
            )
        )
    return Request(label, entry["signed_name"], unsigned_data)


def check_key_file(key, certificate):
    """Checks that a certificate in the key file, if there is one, is the expected certificate."""
    if not key.is_file():
        raise ValueError("--key must name a private key file")
    if key.stat().st_mode & 0o077:
        print("warning: the private key file is accessible by other users", file=sys.stderr)
    blocks = _PEM_CERTIFICATE.findall(key.read_bytes())
    if len(blocks) > 1:
        raise ValueError("the key file holds more than one certificate")
    if blocks and secure_boot.isolated_certificate_der(blocks[0]) != certificate:
        raise ValueError("the certificate in the key file is not --certificate")


def _encode_der(tag, value):
    length = len(value)
    if length < 0x80:
        return bytes([tag, length]) + value
    size = (length.bit_length() + 7) // 8
    return bytes([tag, 0x80 | size]) + length.to_bytes(size, "big") + value


def _certificate_key(certificate):
    """Returns the issuer, serial number and RSA modulus and exponent of a DER certificate."""
    tbs = secure_boot.der_read(certificate)[0].children()[0].children()
    if tbs[0].tag == 0xA0:
        tbs = tbs[1:]
    algorithm, public_key = tbs[5].children()
    if secure_boot.algorithm_oid(algorithm) != _OID_RSA_ENCRYPTION or public_key.value[:1] != b"\0":
        raise ValueError("the certificate does not hold an RSA public key")
    modulus, exponent = secure_boot.der_read(public_key.value[1:])[0].children()
    return tbs[2], tbs[0], int.from_bytes(modulus.value, "big"), int.from_bytes(exponent.value, "big")


def _signed_attributes_digest(attributes, content_digest):
    """Returns the digest that the signature covers and the signingTime, or None, after checking the attributes."""
    values = {}
    for attribute in attributes.children():
        oid, attribute_values = attribute.children()
        values.setdefault(secure_boot.der_oid(oid), []).append(attribute_values.children())
    digests = values.get(_OID_MESSAGE_DIGEST, [])
    if len(digests) != 1 or len(digests[0]) != 1 or digests[0][0].value != content_digest:
        raise ValueError("the signed messageDigest does not match the Authenticode content")
    content_types = values.get(_OID_CONTENT_TYPE, [])
    if len(content_types) != 1 or secure_boot.der_oid(content_types[0][0]) != secure_boot.OID_SPC_INDIRECT_DATA:
        raise ValueError("the signed contentType is not SpcIndirectDataContent")
    signing_times = values.get(_OID_SIGNING_TIME, [])
    if len(signing_times) > 1 or any(len(times) != 1 for times in signing_times):
        raise ValueError("the signature has more than one signingTime")
    signing_time = secure_boot.der_time(signing_times[0][0]) if signing_times else None
    return hashlib.sha256(_encode_der(0x31, attributes.value)).digest(), signing_time


def verify_signature(payload, certificate):
    """Returns the signingTime of the one SignerInfo of payload, or None if it has none.

    Raises ValueError unless the SignerInfo names certificate and its RSA signature verifies.
    """
    signed = secure_boot.parse_signed_data(payload)
    content = signed[2].children()[1].children()[0]
    signer = signed[-1].children()[0].children()
    issuer, serial, modulus, exponent = _certificate_key(certificate)
    identifier = signer[1].children()
    if [(item.tag, item.value) for item in identifier] != [(issuer.tag, issuer.value), (serial.tag, serial.value)]:
        raise ValueError("the signature does not name --certificate as its signer")
    # PKCS #7 version 1.5 digests the contents octets of SpcIndirectDataContent, without its tag and length.
    digest = hashlib.sha256(content.value).digest()
    signing_time = None
    if signer[3].tag == 0xA0:
        digest, signing_time = _signed_attributes_digest(signer[3], digest)
    signature = signer[5 if signer[3].tag == 0xA0 else 4].value
    size = (modulus.bit_length() + 7) // 8
    suffix = b"\0" + _SHA256_DIGEST_INFO + digest
    expected = b"\0\1" + b"\xff" * (size - 2 - len(suffix)) + suffix
    if (
        len(signature) != size
        or pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(size, "big") != expected
    ):
        raise ValueError("the signature does not verify with --certificate; is --key its private key?")
    return signing_time


def check_signing_time(certificate, signing_time):
    """Raises ValueError unless signing_time, in Unix seconds, lies within the validity of the DER certificate."""
    not_before, not_after = secure_boot.certificate_validity(certificate)
    if not not_before <= signing_time <= not_after:
        raise ValueError(
            "signing time {} ({} UTC) is outside the validity of --certificate, {} to {} UTC; "
            "sign at a time inside it, such as the commit time of the release".format(
                signing_time,
                secure_boot.utc_time(signing_time),
                secure_boot.utc_time(not_before),
                secure_boot.utc_time(not_after),
            )
        )


def _run_debian_sbsign(launcher, key, work, signing_time):
    """Signs work/unsigned.efi with the pinned systemd-sbsign; the key is bind-mounted read-only, never copied."""
    tools_scratch = work.parent / (work.name + "-debian-tools")
    if ":" in str(key) or ":" in str(work):
        raise ValueError("the key and scratch paths must not contain ':' for the Debian tools; use --sbsign")
    command = [
        launcher,
        "--ro-bind",
        "{}:/inputs/signing-key".format(key),
        "--rw-bind",
        "{}:/outputs/work".format(work),
        *secure_boot.sbsign_command(
            signing_time,
            "sign",
            "--private-key=/inputs/signing-key",
            "--certificate=/outputs/work/certificate.pem",
            "--output=/outputs/work/signed.efi",
            "/outputs/work/unsigned.efi",
        ),
    ]
    try:
        subprocess.run(command, check=True, env=dict(os.environ, MKOSI_DEBIAN_TOOLS_SCRATCH=str(tools_scratch)))
    except subprocess.CalledProcessError as error:
        raise ValueError(
            "the pinned systemd-sbsign failed with exit status {}; where unprivileged user namespaces are blocked, "
            "for example by AppArmor on Ubuntu 24.04, sign with a host tool through --sbsign".format(error.returncode)
        ) from error
    finally:
        shutil.rmtree(tools_scratch, ignore_errors=True)


def _run_host_sbsign(args, work):
    """Signs work/unsigned.efi with a host systemd-sbsign or sbsigntools' sbsign, under faketime at a signing time."""
    if Path(args.sbsign).name == "systemd-sbsign":
        options = ["sign", "--private-key", args.key, "--certificate", work / "certificate.pem"]
    else:
        options = ["--key", args.key, "--cert", work / "certificate.pem"]
    command = [args.sbsign, *options, "--output", work / "signed.efi", work / "unsigned.efi"]
    env = None
    if args.signing_time is not None:
        variables = secure_boot.faketime_variables(args.signing_time)
        command = [args.faketime, "-f", variables["FAKETIME"], *command]
        env = dict(os.environ, **variables)
    subprocess.run(command, check=True, env=env)


def sign_request(args, request, certificate, scratch):
    """Signs one validated request in a new scratch directory and returns the verified signed binary."""
    work = Path(tempfile.mkdtemp(prefix="request-", dir=scratch)).resolve()
    (work / "certificate.pem").write_bytes(secure_boot.certificate_pem(certificate))
    (work / "unsigned.efi").write_bytes(request.unsigned_data)
    if args.sbsign:
        _run_host_sbsign(args, work)
    else:
        _run_debian_sbsign(args.debian_tools, args.key, work, args.signing_time)
    signed_data = (work / "signed.efi").read_bytes()
    payload = secure_boot.verify_embedded_digest(request.unsigned_data, signed_data)
    signing_time = verify_signature(payload, certificate)
    if args.signing_time is not None and signing_time not in (None, args.signing_time):
        raise ValueError(
            "{}: the signing tool wrote the signingTime {} instead of {}".format(
                request.label, signing_time, args.signing_time
            )
        )
    return signed_data


def write_signed(output_dir, name, data):
    """Atomically writes data to output_dir/name."""
    output_dir.mkdir(parents=True, exist_ok=True)
    partial = output_dir / ".{}.partial".format(name)
    partial.write_bytes(data)
    partial.replace(output_dir / name)


def _user_path(value):
    """Returns value as an absolute path; relative paths are relative to the directory that bazel run started in."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(os.environ.get("BUILD_WORKING_DIRECTORY", ".")) / path
    return path.absolute()


def _runfile(value):
    """Returns the path of a runfile given by its runfiles path, or value itself if it is absolute."""
    if os.path.isabs(value):
        return value
    from python.runfiles import runfiles

    resolver = runfiles.Create()
    path = resolver.Rlocation(value) if resolver else None
    if not path or not os.path.exists(path):
        raise ValueError("runfile {} is missing; run the signer with bazel run".format(value))
    return path


def _signing_time(value):
    """Returns a signing time given in Unix seconds."""
    if not re.fullmatch(r"[0-9]+", value) or int(value) > _MAX_SIGNING_TIME:
        raise argparse.ArgumentTypeError(
            "{!r} is not a Unix time in seconds from 0 to {}".format(value, _MAX_SIGNING_TIME)
        )
    return int(value)


def _parser():
    parser = argparse.ArgumentParser(
        prog="secure_boot_signer",
        description="Validates and Authenticode-signs the requests of a secure_boot_signing_manifest.",
    )
    parser.add_argument("--manifest", type=_user_path, required=True, help="The signing manifest JSON file.")
    parser.add_argument(
        "--certificate", type=_user_path, required=True, help="The expected signer certificate, PEM or DER."
    )
    parser.add_argument("--key", type=_user_path, help="The certificate's private key file, read in place.")
    parser.add_argument("--output-dir", type=_user_path, help="Directory for the signed binaries.")
    parser.add_argument(
        "--execroot", type=_user_path, help="Directory that the manifest's paths are relative to (default: detected)."
    )
    parser.add_argument(
        "--sbsign", help="Host systemd-sbsign or sbsigntools sbsign to use instead of the pinned systemd-sbsign."
    )
    parser.add_argument("--scratch", type=_user_path, help="Parent of the temporary directory (default: TMPDIR).")
    parser.add_argument(
        "--signing-time",
        type=_signing_time,
        metavar="SECONDS",
        help="Unix time to write as the signingTime of every signature, which makes signing deterministic; it must "
        "lie within the certificate's validity, for example the commit time of the release (default: "
        "SOURCE_DATE_EPOCH if it is set, else the current time). With --sbsign, faketime must be on PATH.",
    )
    parser.add_argument("--validate-only", action="store_true", help="Validate the requests; do not sign.")
    parser.add_argument("--debian-tools", help=argparse.SUPPRESS)
    return parser


def _parse_arguments(argv):
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.validate_only and (args.key is None or args.output_dir is None):
        parser.error("--key and --output-dir are required unless --validate-only is set")
    if not args.validate_only and not args.sbsign and not args.debian_tools:
        parser.error("--sbsign is required outside bazel run")
    if args.sbsign:
        found = shutil.which(args.sbsign) if "/" not in args.sbsign else str(_user_path(args.sbsign))
        if not found:
            parser.error("--sbsign {} is not an executable".format(args.sbsign))
        args.sbsign = found
    if args.signing_time is None and os.environ.get("SOURCE_DATE_EPOCH"):
        try:
            args.signing_time = _signing_time(os.environ["SOURCE_DATE_EPOCH"])
        except argparse.ArgumentTypeError as error:
            parser.error("SOURCE_DATE_EPOCH: {}".format(error))
    if args.sbsign and args.signing_time is not None and not args.validate_only:
        args.faketime = shutil.which("faketime")
        if not args.faketime:
            parser.error(
                "a signing time from --signing-time or SOURCE_DATE_EPOCH needs libfaketime's faketime on PATH with "
                "--sbsign; install it, or sign with the pinned systemd-sbsign"
            )
    return args


def sign_manifest(args):
    """Validates every request of the manifest, then signs them all and writes the signed binaries."""
    certificate = secure_boot.certificate_der(args.certificate)
    execroot = args.execroot or find_execroot(args.manifest)
    requests = [validate_entry(execroot, entry, certificate) for entry in load_manifest(args.manifest)]
    if args.signing_time is not None:
        check_signing_time(certificate, args.signing_time)
    if args.validate_only:
        for request in requests:
            print("valid: {} -> {}".format(request.label, request.signed_name))
        return
    check_key_file(args.key, certificate)
    if not args.sbsign:
        args.debian_tools = _runfile(args.debian_tools)
    with tempfile.TemporaryDirectory(prefix="secure-boot-signer-", dir=args.scratch) as scratch:
        signed = [sign_request(args, request, certificate, scratch) for request in requests]
    for request, data in zip(requests, signed, strict=True):
        write_signed(args.output_dir, request.signed_name, data)
        print("signed: {} -> {}".format(request.label, args.output_dir / request.signed_name))


def main(argv=None):
    args = _parse_arguments(argv)
    try:
        sign_manifest(args)
    except (OSError, ValueError, KeyError, IndexError, subprocess.CalledProcessError) as error:
        raise SystemExit("SECURE_BOOT_SIGNER_INVALID: {}".format(error)) from error


if __name__ == "__main__":
    main()
