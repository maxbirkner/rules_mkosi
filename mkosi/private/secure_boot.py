#!/usr/bin/python3
"""Create and verify offline Authenticode Secure Boot artifacts."""

import argparse
import base64
import binascii
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
OID_SIGNED_DATA = "1.2.840.113549.1.7.2"
OID_SPC_INDIRECT_DATA = "1.3.6.1.4.1.311.2.1.4"
OID_SHA256 = "2.16.840.1.101.3.4.2.1"
OID_RSA = {"1.2.840.113549.1.1.1", "1.2.840.113549.1.1.11"}
_counter = 0
MAX_DER_BYTES = 16 * 1024 * 1024
MAX_DER_DEPTH = 32
MAX_DER_CHILDREN = 4096


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


def certificate_der(path):
    data = Path(path).read_bytes()
    begin = b"-----BEGIN CERTIFICATE-----"
    end_marker = b"-----END CERTIFICATE-----"
    if begin in data or end_marker in data:
        if data.count(begin) != 1 or data.count(end_marker) != 1:
            raise ValueError("expected exactly one PEM certificate")
        prefix, remainder = data.split(begin, 1)
        body, suffix = remainder.split(end_marker, 1)
        if prefix.strip() or suffix.strip() or b"-----" in body:
            raise ValueError("certificate input has trailing or additional PEM data")
        try:
            data = base64.b64decode(b"".join(body.split()), validate=True)
        except binascii.Error as error:
            raise ValueError("certificate PEM has invalid base64") from error
    item, consumed = der_read(data)
    if item.tag != 0x30 or consumed != len(data):
        raise ValueError("certificate must contain exactly one DER X.509 object")
    return data


def certificate_pem(data):
    body = base64.b64encode(data)
    lines = [body[index:index + 64] for index in range(0, len(body), 64)]
    return b"-----BEGIN CERTIFICATE-----\n" + b"\n".join(lines) + b"\n-----END CERTIFICATE-----\n"


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
    section_count = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    if not section_count or section_count > 96:
        raise ValueError("invalid PE section count")
    if optional + optional_size > len(data):
        raise ValueError("PE optional header is out of bounds")
    magic = struct.unpack_from("<H", data, optional)[0]
    fixed_size = 112 if magic == 0x20B else 96 if magic == 0x10B else -1
    if fixed_size < 0 or optional_size < fixed_size:
        raise ValueError("invalid PE optional header magic or size")
    directory = optional + fixed_size
    directory_count = struct.unpack_from("<I", data, optional + fixed_size - 4)[0]
    if directory_count < 5:
        raise ValueError("PE has fewer than five data directories")
    if directory + directory_count * 8 > optional + optional_size:
        raise ValueError("PE security directory is unavailable")
    checksum = optional + 64
    file_alignment = struct.unpack_from("<I", data, optional + 36)[0]
    size_headers = struct.unpack_from("<I", data, optional + 60)[0]
    if file_alignment < 0x200 or file_alignment & (file_alignment - 1):
        raise ValueError("invalid PE FileAlignment")
    section_table = optional + optional_size
    section_table_end = section_table + section_count * 40
    if section_table_end > len(data) or size_headers < section_table_end or size_headers > len(data):
        raise ValueError("invalid PE section table or SizeOfHeaders")
    if size_headers % file_alignment:
        raise ValueError("PE SizeOfHeaders is not file aligned")
    sections = []
    for index in range(section_count):
        entry = section_table + index * 40
        raw_size, raw_offset = struct.unpack_from("<II", data, entry + 16)
        if raw_size:
            if raw_offset < size_headers or raw_offset % file_alignment or raw_offset + raw_size > len(data):
                raise ValueError("PE section raw data is out of bounds")
            sections.append((raw_offset, raw_size))
    sections.sort()
    for previous, current in zip(sections, sections[1:]):
        if previous[0] + previous[1] > current[0]:
            raise ValueError("PE section raw data overlaps")
    certificate_offset, certificate_size = struct.unpack_from("<II", data, directory + 32)
    if signed:
        if not certificate_offset or certificate_offset % 8 or certificate_size < 8:
            raise ValueError("missing or unaligned Authenticode certificate table")
        if certificate_offset + certificate_size != len(data):
            raise ValueError("certificate table bounds or trailing data are invalid")
    elif certificate_offset or certificate_size:
        raise ValueError("requested UKI is already signed")
    return {
        "certificate_offset": certificate_offset,
        "certificate_size": certificate_size,
        "checksum": checksum,
        "security_directory": directory + 32,
        "sections": sections,
        "size_headers": size_headers,
    }


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
    item, end = der_read(payload)
    if item.tag != 0x30:
        raise ValueError("Authenticode payload is not DER SignedData")
    if any(payload[end:]):
        raise ValueError("invalid Authenticode DER bounds or padding")
    return payload[:end]


def prove_equivalence(unsigned_data, signed_data):
    unsigned = parse_pe(unsigned_data, False)
    signed = parse_pe(signed_data, True)
    if (unsigned["checksum"], unsigned["security_directory"]) != (signed["checksum"], signed["security_directory"]):
        raise ValueError("PE layouts differ")
    certificate_offset = signed["certificate_offset"]
    certificate_size = signed["certificate_size"]
    if certificate_offset < len(unsigned_data):
        raise ValueError("Authenticode table overlaps requested UKI")
    signed_prefix = bytearray(signed_data[:len(unsigned_data)])
    unsigned_prefix = bytearray(unsigned_data)
    for offset, size in ((unsigned["checksum"], 4), (unsigned["security_directory"], 8)):
        signed_prefix[offset:offset + size] = unsigned_prefix[offset:offset + size]
    if signed_prefix != unsigned_prefix:
        raise ValueError("signed UKI differs from requested unsigned UKI")
    if any(signed_data[len(unsigned_data):certificate_offset]):
        raise ValueError("nonzero data inserted before Authenticode table")
    return authenticode_payload(signed_data, certificate_offset, certificate_size)


def authenticode_hash(data, pe):
    digest = hashlib.sha256()
    checksum = pe["checksum"]
    security = pe["security_directory"]
    digest.update(data[:checksum])
    digest.update(data[checksum + 4:security])
    digest.update(data[security + 8:pe["size_headers"]])
    end = pe["size_headers"]
    for offset, size in pe["sections"]:
        if offset < end:
            raise ValueError("PE section order overlaps hashed content")
        digest.update(data[offset:offset + size])
        end = offset + size
    certificate_offset = pe["certificate_offset"] or len(data)
    if end > certificate_offset:
        raise ValueError("certificate table overlaps PE content")
    digest.update(data[end:certificate_offset])
    return digest.digest()


class Der:
    def __init__(self, tag, value, depth):
        self.tag = tag
        self.value = value
        self.depth = depth

    def children(self):
        if self.depth >= MAX_DER_DEPTH:
            raise ValueError("DER nesting exceeds limit")
        result = []
        cursor = 0
        while cursor < len(self.value):
            if len(result) >= MAX_DER_CHILDREN:
                raise ValueError("DER child count exceeds limit")
            item, cursor = der_read(self.value, cursor, self.depth + 1)
            result.append(item)
        return result


def der_read(data, offset=0, depth=0):
    if len(data) > MAX_DER_BYTES or depth > MAX_DER_DEPTH:
        raise ValueError("DER resource limit exceeded")
    if offset + 2 > len(data):
        raise ValueError("truncated DER object")
    tag = data[offset]
    length = data[offset + 1]
    cursor = offset + 2
    if length & 0x80:
        count = length & 0x7F
        if not count:
            raise ValueError("indefinite DER length is forbidden")
        if count > 4 or cursor + count > len(data):
            raise ValueError("invalid DER length")
        if data[cursor] == 0:
            raise ValueError("nonminimal DER length")
        length = int.from_bytes(data[cursor:cursor + count], "big")
        if length < 128 or count != (length.bit_length() + 7) // 8:
            raise ValueError("nonminimal DER long-form length")
        cursor += count
    end = cursor + length
    if end > len(data):
        raise ValueError("DER object is out of bounds")
    return Der(tag, data[cursor:end], depth), end


def der_oid(item):
    if item.tag != 0x06 or not item.value or len(item.value) > 256:
        raise ValueError("expected DER object identifier")
    subidentifiers = []
    value = 0
    group_start = True
    for byte in item.value:
        if group_start and byte == 0x80:
            raise ValueError("nonminimal DER OID subidentifier")
        if value > (1 << 63):
            raise ValueError("DER OID subidentifier is too large")
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            subidentifiers.append(value)
            if len(subidentifiers) > 64:
                raise ValueError("DER OID has too many arcs")
            value = 0
            group_start = True
        else:
            group_start = False
    if not group_start:
        raise ValueError("truncated DER object identifier")
    first = subidentifiers[0]
    if first < 40:
        values = [0, first]
    elif first < 80:
        values = [1, first - 40]
    else:
        values = [2, first - 80]
    return ".".join(map(str, values))


def algorithm_oid(item):
    children = item.children()
    if item.tag != 0x30 or not children:
        raise ValueError("invalid AlgorithmIdentifier")
    return der_oid(children[0])


def authenticode_facts(payload):
    outer, end = der_read(payload)
    outer_children = outer.children()
    if outer.tag != 0x30 or end != len(payload) or len(outer_children) != 2:
        raise ValueError("invalid Authenticode ContentInfo")
    if der_oid(outer_children[0]) != OID_SIGNED_DATA or outer_children[1].tag != 0xA0:
        raise ValueError("AuthentiCode is not PKCS7 SignedData")
    signed_wrapper = outer_children[1].children()
    if len(signed_wrapper) != 1 or signed_wrapper[0].tag != 0x30:
        raise ValueError("invalid SignedData wrapper")
    signed = signed_wrapper[0].children()
    if len(signed) < 4 or signed[1].tag != 0x31:
        raise ValueError("invalid SignedData fields")
    digest_algorithms = signed[1].children()
    if len(digest_algorithms) != 1 or algorithm_oid(digest_algorithms[0]) != OID_SHA256:
        raise ValueError("SignedData must declare exactly SHA-256")
    content = signed[2].children()
    if len(content) != 2 or der_oid(content[0]) != OID_SPC_INDIRECT_DATA or content[1].tag != 0xA0:
        raise ValueError("missing Authenticode SpcIndirectDataContent")
    indirect_wrappers = content[1].children()
    if len(indirect_wrappers) != 1 or indirect_wrappers[0].tag != 0x30:
        raise ValueError("invalid SpcIndirectDataContent")
    indirect = indirect_wrappers[0].children()
    if len(indirect) != 2:
        raise ValueError("invalid SpcIndirectDataContent fields")
    digest_info = indirect[1].children()
    if len(digest_info) != 2 or algorithm_oid(digest_info[0]) != OID_SHA256 or digest_info[1].tag != 0x04:
        raise ValueError("invalid Authenticode image digest")
    signer_infos = signed[-1]
    signers = signer_infos.children()
    if signer_infos.tag != 0x31 or len(signers) != 1:
        raise ValueError("AuthentiCode must have exactly one SignerInfo")
    signer = signers[0].children()
    if len(signer) < 5:
        raise ValueError("invalid SignerInfo")
    if algorithm_oid(signer[2]) != OID_SHA256:
        raise ValueError("SignerInfo digest algorithm is not SHA-256")
    signature_index = 4 if signer[3].tag != 0xA0 else 5
    if signature_index >= len(signer) or algorithm_oid(signer[signature_index - 1]) not in OID_RSA:
        raise ValueError("unsupported SignerInfo signature algorithm")
    if signer[signature_index].tag != 0x04:
        raise ValueError("missing SignerInfo signature")
    return digest_info[1].value


def create_request(args):
    if args.algorithm != ALGORITHM:
        raise ValueError("unsupported signing algorithm")
    parse_pe(Path(args.unsigned_uki).read_bytes(), False)
    normalized_certificate = certificate_der(args.certificate)
    Path(args.normalized_certificate).write_bytes(certificate_pem(normalized_certificate))
    document = {
        "certificate_sha256": hashlib.sha256(normalized_certificate).hexdigest(),
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
    expected_certificate = certificate_der(args.certificate)
    fingerprint = hashlib.sha256(expected_certificate).hexdigest()
    if fingerprint != request["certificate_sha256"]:
        raise ValueError("signer certificate does not match request")
    unsigned_data = Path(args.unsigned_uki).read_bytes()
    signed_data = Path(args.signed_uki).read_bytes()
    payload = prove_equivalence(unsigned_data, signed_data)
    embedded_digest = authenticode_facts(payload)
    computed_digest = authenticode_hash(signed_data, parse_pe(signed_data, True))
    if embedded_digest != computed_digest:
        raise ValueError("embedded Authenticode digest does not match imported PE")
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
        "-signer",
        args.verified_signer,
        "-out",
        args.content,
    )
    verified_signer = certificate_der(args.verified_signer)
    if verified_signer != expected_certificate:
        raise ValueError("verified SignerInfo certificate does not match request")
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
        if args.other_unsigned:
            run_tool(
                args.sbsign,
                "/usr/lib/systemd/systemd-sbsign",
                "sign",
                "--private-key",
                str(key),
                "--certificate",
                args.certificate,
                "--output",
                args.other_signed,
                args.other_unsigned,
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
    request.add_argument("--normalized-certificate", required=True)
    request.add_argument("--algorithm", required=True)
    request.add_argument("--output", required=True)
    request.add_argument("--digest-output", required=True)
    request.set_defaults(function=create_request)
    verify_parser = commands.add_parser("verify")
    for name in ("openssl", "request", "request-digest", "unsigned-uki", "signed-uki", "certificate", "pkcs7", "content", "verified-signer", "output", "metadata"):
        verify_parser.add_argument("--" + name, required=True)
    verify_parser.set_defaults(function=verify)
    fixture = commands.add_parser("ephemeral-fixture")
    for name in ("openssl", "sbsign", "unsigned-uki", "certificate", "signed-uki", "scratch"):
        fixture.add_argument("--" + name, required=True)
    fixture.add_argument("--other-unsigned")
    fixture.add_argument("--other-signed")
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
