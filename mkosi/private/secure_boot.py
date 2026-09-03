#!/usr/bin/python3
"""Create and verify offline Authenticode Secure Boot artifacts."""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path


REQUEST_FORMAT = "mkosi-secure-boot-signing-request-v2"
SIGNED_FORMAT = "mkosi-secure-boot-signed-uki-v2"
ALGORITHM = "authenticode-sha256"
_counter = 0


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _launcher(tool, arguments):
    global _counter
    if Path(tool).name != "launcher":
        return [tool] + arguments, None
    _counter += 1
    cwd = os.getcwd()
    env = dict(os.environ)
    env["MKOSI_DEBIAN_TOOLS_SCRATCH"] = os.path.join(
        cwd, ".secure-boot-tool-{}-{}".format(os.getpid(), _counter)
    )
    return [
        tool,
        "--rw-bind",
        "{}:/outputs/work".format(cwd),
        arguments[0],
    ] + [
        value if value.startswith("-") or value.startswith("/") or "/" not in value else "/outputs/work/" + value
        for value in arguments[1:]
    ], env


def run_tool(tool, *arguments, capture=False):
    command, env = _launcher(tool, list(arguments))
    return subprocess.run(command, check=True, capture_output=capture, env=env)


def certificate_sha256(openssl, certificate):
    result = run_tool(openssl, "/usr/bin/openssl", "x509", "-in", certificate, "-outform", "DER", capture=True)
    return hashlib.sha256(result.stdout).hexdigest()


def write_json(path, document):
    Path(path).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def request_digest(document):
    return hashlib.sha256(
        (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


def parse_pe(data, signed):
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("UKI is not a PE/COFF image")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe > len(data) - 24 or data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("invalid PE header bounds")
    optional = pe + 24
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    if optional + optional_size > len(data):
        raise ValueError("PE optional header is out of bounds")
    magic = struct.unpack_from("<H", data, optional)[0]
    directory = optional + (112 if magic == 0x20B else 96 if magic == 0x10B else -1)
    if directory < optional or directory + 40 > optional + optional_size:
        raise ValueError("PE security directory is unavailable")
    checksum = optional + 64
    certificate_offset, certificate_size = struct.unpack_from("<II", data, directory + 32)
    if signed:
        if not certificate_offset or certificate_offset % 8 or certificate_size < 8:
            raise ValueError("missing or unaligned Authenticode certificate table")
        if certificate_offset + certificate_size != len(data):
            raise ValueError("certificate table bounds or trailing data are invalid")
    elif certificate_offset or certificate_size:
        raise ValueError("requested UKI is already signed")
    return checksum, directory + 32, certificate_offset, certificate_size


def authenticode_payload(signed_data, certificate_offset, certificate_size):
    cursor = certificate_offset
    end = certificate_offset + certificate_size
    certificates = []
    while cursor < end:
        if end - cursor < 8:
            raise ValueError("truncated WIN_CERTIFICATE header")
        length, revision, certificate_type = struct.unpack_from("<IHH", signed_data, cursor)
        if length < 8 or cursor + length > end:
            raise ValueError("WIN_CERTIFICATE is out of bounds")
        if revision != 0x200 or certificate_type != 2:
            raise ValueError("unsupported WIN_CERTIFICATE structure")
        certificates.append(_der_object(signed_data[cursor + 8:cursor + length]))
        aligned = (length + 7) & ~7
        if cursor + aligned > end or any(signed_data[cursor + length:cursor + aligned]):
            raise ValueError("invalid WIN_CERTIFICATE padding")
        cursor += aligned
    if cursor != end or len(certificates) != 1:
        raise ValueError("ambiguous or duplicate Authenticode certificate table")
    return certificates[0]


def _der_object(payload):
    if len(payload) < 2 or payload[0] != 0x30:
        raise ValueError("Authenticode payload is not DER SignedData")
    first_length = payload[1]
    if first_length < 0x80:
        header = 2
        body_length = first_length
    else:
        length_bytes = first_length & 0x7F
        if not length_bytes or length_bytes > 4 or 2 + length_bytes > len(payload):
            raise ValueError("invalid Authenticode DER length")
        header = 2 + length_bytes
        body_length = int.from_bytes(payload[2:header], "big")
    end = header + body_length
    if end > len(payload) or any(payload[end:]):
        raise ValueError("invalid Authenticode DER bounds or padding")
    return payload[:end]


def prove_equivalence(unsigned_data, signed_data):
    unsigned_checksum, unsigned_directory, _, _ = parse_pe(unsigned_data, False)
    signed_checksum, signed_directory, certificate_offset, certificate_size = parse_pe(signed_data, True)
    if (unsigned_checksum, unsigned_directory) != (signed_checksum, signed_directory):
        raise ValueError("PE layouts differ")
    if certificate_offset < len(unsigned_data):
        raise ValueError("Authenticode table overlaps requested UKI")
    signed_prefix = bytearray(signed_data[:len(unsigned_data)])
    unsigned_prefix = bytearray(unsigned_data)
    for offset, size in ((unsigned_checksum, 4), (unsigned_directory, 8)):
        signed_prefix[offset:offset + size] = unsigned_prefix[offset:offset + size]
    if signed_prefix != unsigned_prefix:
        raise ValueError("signed UKI differs from requested unsigned UKI")
    if any(signed_data[len(unsigned_data):certificate_offset]):
        raise ValueError("nonzero data inserted before Authenticode table")
    return authenticode_payload(signed_data, certificate_offset, certificate_size)


def create_request(args):
    if args.algorithm != ALGORITHM:
        raise ValueError("unsupported signing algorithm")
    parse_pe(Path(args.unsigned_uki).read_bytes(), False)
    document = {
        "certificate_sha256": certificate_sha256(args.openssl, args.certificate),
        "context": "uefi-secure-boot-uki",
        "format_version": REQUEST_FORMAT,
        "signature_algorithm": ALGORITHM,
        "unsigned_uki_sha256": sha256(args.unsigned_uki),
    }
    write_json(args.output, document)
    Path(args.digest_output).write_text(request_digest(document) + "\n")


def verify(args):
    request = json.loads(Path(args.request).read_text())
    expected = {
        "certificate_sha256",
        "context",
        "format_version",
        "signature_algorithm",
        "unsigned_uki_sha256",
    }
    if set(request) != expected or request["format_version"] != REQUEST_FORMAT:
        raise ValueError("invalid signing request schema")
    recorded_request_digest = Path(args.request_digest).read_text().strip()
    if recorded_request_digest != request_digest(request):
        raise ValueError("signing request digest does not match request")
    if request["context"] != "uefi-secure-boot-uki" or request["signature_algorithm"] != ALGORITHM:
        raise ValueError("wrong signing context or algorithm")
    if sha256(args.unsigned_uki) != request["unsigned_uki_sha256"]:
        raise ValueError("unsigned UKI no longer matches its request")
    fingerprint = certificate_sha256(args.openssl, args.certificate)
    if fingerprint != request["certificate_sha256"]:
        raise ValueError("signer certificate does not match request")
    payload = prove_equivalence(
        Path(args.unsigned_uki).read_bytes(),
        Path(args.signed_uki).read_bytes(),
    )
    Path(args.pkcs7).write_bytes(payload)
    run_tool(
        args.openssl,
        "/usr/bin/openssl",
        "smime",
        "-verify",
        "-inform",
        "DER",
        "-in",
        args.pkcs7,
        "-certfile",
        args.certificate,
        "-nointern",
        "-noverify",
        "-out",
        args.content,
    )
    printed = run_tool(
        args.openssl,
        "/usr/bin/openssl",
        "pkcs7",
        "-print",
        "-inform",
        "DER",
        "-in",
        args.pkcs7,
        capture=True,
    ).stdout.decode(errors="replace")
    if "algorithm: sha256 " not in printed:
        raise ValueError("embedded Authenticode signature does not use SHA-256")
    shutil.copyfile(args.signed_uki, args.output)
    write_json(args.metadata, {
        "certificate_sha256": fingerprint,
        "format_version": SIGNED_FORMAT,
        "request_digest": recorded_request_digest,
        "signed_uki_sha256": sha256(args.signed_uki),
        "unsigned_uki_sha256": request["unsigned_uki_sha256"],
        "verification": "embedded-authenticode-sha256",
    })


def ephemeral_fixture(args):
    scratch = Path(args.scratch)
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(mode=0o700)
    key = scratch / "ephemeral-private-key.pem"
    try:
        run_tool(args.openssl, "/usr/bin/openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(key))
        run_tool(
            args.openssl,
            "/usr/bin/openssl",
            "req",
            "-new",
            "-x509",
            "-key",
            str(key),
            "-out",
            args.certificate,
            "-days",
            "1",
            "-subj",
            "/CN=rules_mkosi ephemeral test signer/",
        )
        run_tool(
            args.sbsign,
            "/usr/lib/systemd/systemd-sbsign",
            "sign",
            "--private-key",
            str(key),
            "--certificate",
            args.certificate,
            "--output",
            args.signed_uki,
            args.unsigned_uki,
        )
    finally:
        if key.exists():
            key.write_bytes(b"\0" * key.stat().st_size)
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(required=True)
    request = commands.add_parser("request")
    request.add_argument("--openssl", required=True)
    request.add_argument("--unsigned-uki", required=True)
    request.add_argument("--certificate", required=True)
    request.add_argument("--algorithm", required=True)
    request.add_argument("--output", required=True)
    request.add_argument("--digest-output", required=True)
    request.set_defaults(function=create_request)
    verify_parser = commands.add_parser("verify")
    for name in ("openssl", "request", "request-digest", "unsigned-uki", "signed-uki", "certificate", "pkcs7", "content", "output", "metadata"):
        verify_parser.add_argument("--" + name, required=True)
    verify_parser.set_defaults(function=verify)
    fixture = commands.add_parser("ephemeral-fixture")
    for name in ("openssl", "sbsign", "unsigned-uki", "certificate", "signed-uki", "scratch"):
        fixture.add_argument("--" + name, required=True)
    fixture.set_defaults(function=ephemeral_fixture)
    args = parser.parse_args()
    try:
        args.function(args)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        detail = getattr(error, "stderr", None)
        if isinstance(detail, bytes):
            detail = detail.decode(errors="replace")
        raise SystemExit("SECURE_BOOT_INVALID: {}".format(detail or error))


if __name__ == "__main__":
    main()
