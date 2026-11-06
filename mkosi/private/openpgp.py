#!/usr/bin/python3
"""The OpenPGP (RFC 4880) packet framing that offline sysupdate manifest signing needs.

It reads public certificates and detached signatures without verifying them; the sqv tool verifies signatures. It also
encodes the version 4 RSA keys and signatures of the ephemeral test signer.
"""

import base64
import hashlib
import re
import struct

TAG_SIGNATURE = 2
TAG_SECRET_KEY = 5
TAG_PUBLIC_KEY = 6
TAG_SECRET_SUBKEY = 7
TAG_TRUST = 12
TAG_USER_ID = 13
TAG_PUBLIC_SUBKEY = 14
TAG_USER_ATTRIBUTE = 17

_CERTIFICATE_TAGS = {TAG_PUBLIC_KEY, TAG_SIGNATURE, TAG_TRUST, TAG_USER_ID, TAG_PUBLIC_SUBKEY, TAG_USER_ATTRIBUTE}
_ARMOR = re.compile(
    rb"-----BEGIN PGP (?P<label>[A-Z ]+)-----\r?\n(?:[^\r\n]+\r?\n)*?\r?\n(?P<body>.*?)-----END PGP (?P=label)-----",
    re.DOTALL,
)


def crc24(data):
    """Returns the CRC-24 checksum of ASCII armor (RFC 4880 section 6.1)."""
    crc = 0xB704CE
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def dearmor(data, label):
    """Returns binary OpenPGP data, decoding one ASCII-armored block with the given label.

    Raises:
        ValueError: if armored data has another label, a bad checksum or surrounding text.
    """
    if not data.lstrip().startswith(b"-----BEGIN PGP "):
        return data
    match = _ARMOR.fullmatch(data.strip())
    if not match or match["label"] != label.encode():
        raise ValueError("expected one ASCII-armored 'PGP {}' block".format(label))
    lines = match["body"].split()
    checksum = None
    if lines and lines[-1].startswith(b"="):
        checksum = base64.b64decode(lines.pop()[1:], validate=True)
    binary = base64.b64decode(b"".join(lines), validate=True)
    if checksum is not None and checksum != crc24(binary).to_bytes(3, "big"):
        raise ValueError("ASCII armor checksum mismatch")
    return binary


def _header(data, offset):
    """Returns the tag, body offset and body length of the packet at offset."""
    first = data[offset]
    if not first & 0x80:
        raise ValueError("invalid OpenPGP packet header at byte {}".format(offset))
    if not first & 0x40:
        length_bytes = (1, 2, 4, None)[first & 0x03]
        if length_bytes is None:
            raise ValueError("indeterminate OpenPGP packet lengths are not supported")
        start = offset + 1 + length_bytes
        return (first >> 2) & 0x0F, start, int.from_bytes(data[offset + 1 : start], "big")
    octet = data[offset + 1]
    if octet < 192:
        return first & 0x3F, offset + 2, octet
    if octet < 224:
        return first & 0x3F, offset + 3, ((octet - 192) << 8) + data[offset + 2] + 192
    if octet == 255:
        return first & 0x3F, offset + 6, int.from_bytes(data[offset + 2 : offset + 6], "big")
    raise ValueError("partial OpenPGP packet lengths are not supported")


def packets(data):
    """Returns the (tag, body) pairs of binary OpenPGP data.

    Raises:
        ValueError: if the data is empty or a packet is malformed or truncated.
    """
    result = []
    offset = 0
    while offset < len(data):
        try:
            tag, start, length = _header(data, offset)
        except IndexError as error:
            raise ValueError("truncated OpenPGP packet header") from error
        if start + length > len(data):
            raise ValueError("truncated OpenPGP packet")
        result.append((tag, data[start : start + length]))
        offset = start + length
    if not result:
        raise ValueError("no OpenPGP packets")
    return result


def packet(tag, body):
    """Returns a new-format packet."""
    if len(body) < 192:
        length = bytes([len(body)])
    elif len(body) < 8384:
        length = bytes([((len(body) - 192) >> 8) + 192, (len(body) - 192) & 0xFF])
    else:
        length = b"\xff" + struct.pack(">I", len(body))
    return bytes([0xC0 | tag]) + length + body


def fingerprint(public_key_body):
    """Returns the uppercase hexadecimal fingerprint of a version 4 public key packet body."""
    if not public_key_body or public_key_body[0] != 4:
        raise ValueError("only version 4 OpenPGP keys are supported")
    return hashlib.sha1(b"\x99" + struct.pack(">H", len(public_key_body)) + public_key_body).hexdigest().upper()


def certificate(data):
    """Returns the binary form and primary key fingerprint of one transferable public key (OpenPGP certificate).

    Raises:
        ValueError: for secret keys, several certificates or packets that do not belong in a certificate.
    """
    binary = dearmor(data, "PUBLIC KEY BLOCK")
    parsed = packets(binary)
    tags = [tag for tag, _ in parsed]
    if TAG_SECRET_KEY in tags or TAG_SECRET_SUBKEY in tags:
        raise ValueError("public_key contains secret key material; pass only the public certificate")
    if tags[0] != TAG_PUBLIC_KEY or tags.count(TAG_PUBLIC_KEY) != 1:
        raise ValueError("public_key must contain exactly one OpenPGP certificate")
    if not set(tags) <= _CERTIFICATE_TAGS:
        raise ValueError("public_key contains packets that do not belong in an OpenPGP certificate")
    return binary, fingerprint(parsed[0][1])


def detached_signature(data):
    """Returns the binary form of a detached signature that holds exactly one signature packet.

    systemd-pull (systemd 257) passes the signature to `gpg --verify` and rejects the download unless gpg succeeds,
    which it does not if any signature is by a key outside the device keyring, even when another one is valid.

    Raises:
        ValueError: for other OpenPGP data, such as a signed message, or several signatures.
    """
    binary = dearmor(data, "SIGNATURE")
    tags = [tag for tag, _ in packets(binary)]
    if any(tag != TAG_SIGNATURE for tag in tags):
        raise ValueError("expected a detached OpenPGP signature")
    if len(tags) != 1:
        raise ValueError("expected exactly one OpenPGP signature, found {}".format(len(tags)))
    return binary


def mpi(value):
    """Returns an OpenPGP multiprecision integer."""
    return struct.pack(">H", value.bit_length()) + value.to_bytes((value.bit_length() + 7) // 8, "big")


def rsa_public_key(modulus, exponent, created):
    """Returns the body of a version 4 RSA public key packet."""
    return struct.pack(">BIB", 4, created, 1) + mpi(modulus) + mpi(exponent)


def _subpacket(kind, value):
    return bytes([len(value) + 1, kind]) + value


def rsa_sha256_signature(public_key_body, signature_type, created, signed_data, sign_digest, key_flags=None):
    """Returns the body of a version 4 RSA/SHA-256 signature packet by the key of public_key_body.

    signed_data is the data that RFC 4880 section 5.2.4 hashes before the signature fields, and sign_digest returns the
    PKCS #1 v1.5 signature of a SHA-256 digest as an integer.
    """
    key_fingerprint = bytes.fromhex(fingerprint(public_key_body))
    hashed = _subpacket(2, struct.pack(">I", created)) + _subpacket(33, b"\x04" + key_fingerprint)
    if key_flags is not None:
        hashed += _subpacket(27, bytes([key_flags]))
    fields = struct.pack(">BBBBH", 4, signature_type, 1, 8, len(hashed)) + hashed
    digest = hashlib.sha256(signed_data + fields + b"\x04\xff" + struct.pack(">I", len(fields))).digest()
    unhashed = _subpacket(16, key_fingerprint[-8:])
    return fields + struct.pack(">H", len(unhashed)) + unhashed + digest[:2] + mpi(sign_digest(digest))


def user_id_certification_data(public_key_body, user_id):
    """Returns the data that a certification of user_id on the key hashes."""
    key = b"\x99" + struct.pack(">H", len(public_key_body)) + public_key_body
    return key + b"\xb4" + struct.pack(">I", len(user_id)) + user_id
