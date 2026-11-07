"""Builds and validates UEFI authenticated variable files (.auth) for Secure Boot key enrollment.

An .auth file is an EFI_VARIABLE_AUTHENTICATION_2 header (an EFI_TIME and a WIN_CERTIFICATE_UEFI_GUID with a PKCS#7
SignedData) followed by the variable data, a list of EFI_SIGNATURE_LISTs. systemd-boot writes the files in
/loader/keys/auto/ to the PK, KEK, db and dbx variables when the firmware is in Setup Mode.
"""

import struct
import uuid

EFI_CERT_TYPE_PKCS7 = uuid.UUID("4aafd29d-68df-49ee-8aa9-347d375665a7")
EFI_CERT_X509 = uuid.UUID("a5c059a1-94e4-4aa7-87b5-ab155c2bf072")
EFI_CERT_SHA256 = uuid.UUID("c1c41626-504c-4092-aca9-41f936934328")
EFI_GLOBAL_VARIABLE = uuid.UUID("8be4df61-93ca-11d2-aa0d-00e098032b8c")
EFI_IMAGE_SECURITY_DATABASE = uuid.UUID("d719b2cb-3d3a-4596-a3bc-dad00e67656f")
# NON_VOLATILE | BOOTSERVICE_ACCESS | RUNTIME_ACCESS | TIME_BASED_AUTHENTICATED_WRITE_ACCESS
ATTRIBUTES = 0x27
VARIABLES = {
    "PK": EFI_GLOBAL_VARIABLE,
    "KEK": EFI_GLOBAL_VARIABLE,
    "db": EFI_IMAGE_SECURITY_DATABASE,
    "dbx": EFI_IMAGE_SECURITY_DATABASE,
}
REQUIRED = ("PK", "KEK", "db")
_TIME = struct.Struct("<HBBBBBBIhBB")
_WIN_CERTIFICATE = struct.Struct("<IHH16s")
_SIGNATURE_LIST = struct.Struct("<16sIII")
_WIN_CERT_TYPE_EFI_GUID = 0x0EF1
_WIN_CERT_REVISION = 0x0200


def efi_time(year, month=1, day=1):
    """Returns an EFI_TIME at midnight UTC with the zero fields that time-based authenticated variables require."""
    return _TIME.pack(year, month, day, 0, 0, 0, 0, 0, 0, 0, 0)


def signature_list(certificate_der, owner):
    """Returns an EFI_SIGNATURE_LIST holding one X.509 certificate owned by the owner UUID."""
    size = _SIGNATURE_LIST.size + 16 + len(certificate_der)
    header = _SIGNATURE_LIST.pack(EFI_CERT_X509.bytes_le, size, 0, 16 + len(certificate_der))
    return header + owner.bytes_le + certificate_der


def signed_payload(name, timestamp, data):
    """Returns the bytes that the PKCS#7 signature of variable name with timestamp and data signs."""
    return name.encode("utf-16-le") + VARIABLES[name].bytes_le + struct.pack("<I", ATTRIBUTES) + timestamp + data


def auth_file(timestamp, signed_data, data):
    """Returns an .auth file from its timestamp, the DER PKCS#7 SignedData over signed_payload, and the data."""
    header = _WIN_CERTIFICATE.pack(
        _WIN_CERTIFICATE.size + len(signed_data),
        _WIN_CERT_REVISION,
        _WIN_CERT_TYPE_EFI_GUID,
        EFI_CERT_TYPE_PKCS7.bytes_le,
    )
    return timestamp + header + signed_data + data


def _parse_time(data):
    if len(data) < _TIME.size + _WIN_CERTIFICATE.size:
        raise ValueError("too short for an EFI_VARIABLE_AUTHENTICATION_2 header")
    year, month, day, hour, minute, second, pad1, nanosecond, zone, daylight, pad2 = _TIME.unpack_from(data)
    if not (1 <= month <= 12 and 1 <= day <= 31 and hour < 24 and minute < 60 and second < 60 and year >= 1900):
        raise ValueError("invalid EFI_TIME")
    if pad1 or nanosecond or zone or daylight or pad2:
        raise ValueError("EFI_TIME of a time-based authenticated variable must have zero Pad, Nanosecond, TimeZone")


def _parse_certificate(data):
    """Returns the PKCS#7 bytes and the offset of the variable data after the WIN_CERTIFICATE_UEFI_GUID."""
    length, revision, certificate_type, cert_type = _WIN_CERTIFICATE.unpack_from(data, _TIME.size)
    end = _TIME.size + length
    if revision != _WIN_CERT_REVISION or certificate_type != _WIN_CERT_TYPE_EFI_GUID:
        raise ValueError("authentication header is not a WIN_CERTIFICATE_UEFI_GUID")
    if uuid.UUID(bytes_le=cert_type) != EFI_CERT_TYPE_PKCS7:
        raise ValueError("authentication header does not carry a PKCS#7 signature")
    if length <= _WIN_CERTIFICATE.size or end > len(data):
        raise ValueError("WIN_CERTIFICATE length is out of bounds")
    signed_data = data[_TIME.size + _WIN_CERTIFICATE.size : end]
    if signed_data[:1] != b"\x30":
        raise ValueError("PKCS#7 signature is not DER")
    return signed_data, end


def signature_lists(data):
    """Returns (signature type UUID, [signature data]) for each EFI_SIGNATURE_LIST in data; raises ValueError."""
    lists = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < _SIGNATURE_LIST.size:
            raise ValueError("truncated EFI_SIGNATURE_LIST")
        signature_type, list_size, header_size, signature_size = _SIGNATURE_LIST.unpack_from(data, offset)
        body = offset + _SIGNATURE_LIST.size + header_size
        end = offset + list_size
        if end > len(data) or body > end or signature_size <= 16 or (end - body) % signature_size:
            raise ValueError("EFI_SIGNATURE_LIST sizes are inconsistent")
        entries = [data[start + 16 : start + signature_size] for start in range(body, end, signature_size)]
        if not entries:
            raise ValueError("EFI_SIGNATURE_LIST is empty")
        lists.append((uuid.UUID(bytes_le=signature_type), entries))
        offset = end
    return lists


def parse_auth(name, data):
    """Validates the .auth file data of variable name; returns its PKCS#7 bytes and its signature lists."""
    if name not in VARIABLES:
        raise ValueError("{}.auth is not a Secure Boot variable; expected one of {}".format(name, sorted(VARIABLES)))
    _parse_time(data)
    signed_data, end = _parse_certificate(data)
    lists = signature_lists(data[end:])
    if name == "PK" and (len(lists) != 1 or lists[0][0] != EFI_CERT_X509 or len(lists[0][1]) != 1):
        raise ValueError("PK.auth must hold exactly one X.509 certificate")
    if name in ("KEK", "db") and not any(signature_type == EFI_CERT_X509 for signature_type, _ in lists):
        raise ValueError("{}.auth must hold at least one X.509 certificate".format(name))
    return signed_data, lists


def x509_certificates(lists):
    """Returns the DER X.509 certificates in signature lists."""
    return [entry for signature_type, entries in lists if signature_type == EFI_CERT_X509 for entry in entries]
