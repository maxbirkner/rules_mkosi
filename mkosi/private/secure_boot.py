#!/usr/bin/python3
"""Create and verify the repository's offline Secure Boot exchange artifacts."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


FORMAT = "mkosi-secure-boot-signing-request-v1"
RESPONSE_FORMAT = "mkosi-secure-boot-signing-response-v1"
_scratch_counter = 0


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def crypto_command(openssl, arguments):
    """Runs OpenSSL directly or through the authenticated Debian launcher."""
    if pathlib := Path(openssl):
        if pathlib.name == "launcher":
            return [openssl, "--rw-bind", "{}:/outputs/work".format(os.getcwd()), "/usr/bin/openssl"] + arguments
    return [openssl] + arguments


def bound_path(openssl, path):
    if Path(openssl).name == "launcher":
        return "/outputs/work/" + str(Path(path))
    return str(path)


def crypto_env(openssl):
    global _scratch_counter
    if Path(openssl).name != "launcher":
        return None
    _scratch_counter += 1
    environment = dict(os.environ)
    environment["MKOSI_DEBIAN_TOOLS_SCRATCH"] = os.path.join(
        os.getcwd(), ".secure-boot-crypto-{}-{}".format(os.getpid(), _scratch_counter)
    )
    return environment


def certificate_fingerprint(openssl, certificate):
    result = subprocess.run(
        crypto_command(openssl, ["x509", "-in", bound_path(openssl, certificate), "-outform", "DER"]),
        check=True,
        capture_output=True,
        env=crypto_env(openssl),
    )
    return hashlib.sha256(result.stdout).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def request(args):
    write_json(
        args.output,
        {
            "certificate_sha256": certificate_fingerprint(args.openssl, args.certificate),
            "format_version": FORMAT,
            "signature_algorithm": args.algorithm,
            "unsigned_uki_sha256": digest(args.unsigned_uki),
        },
    )


def response_payload(request_path, signed_uki):
    request_document = json.loads(Path(request_path).read_text())
    if request_document.get("format_version") != FORMAT:
        raise ValueError("unsupported signing request format")
    return {
        "format_version": RESPONSE_FORMAT,
        "request_sha256": digest(request_path),
        "signed_uki_sha256": digest(signed_uki),
    }


def test_response(args):
    payload = response_payload(args.request, args.signed_uki)
    write_json(args.output, payload)
    subprocess.run(
        crypto_command(args.openssl, [
            "dgst",
            "-sha256",
            "-sign",
            bound_path(args.openssl, args.private_key),
            "-out",
            bound_path(args.openssl, args.signature),
            bound_path(args.openssl, args.output),
        ]),
        check=True,
        env=crypto_env(args.openssl),
    )


def verify(args):
    request_document = json.loads(Path(args.request).read_text())
    response_document = json.loads(Path(args.response).read_text())
    if request_document.get("format_version") != FORMAT:
        raise ValueError("unsupported signing request format")
    if response_document != response_payload(args.request, args.signed_uki):
        raise ValueError("response does not bind this request and signed UKI")
    actual_certificate = certificate_fingerprint(args.openssl, args.certificate)
    if actual_certificate != request_document.get("certificate_sha256"):
        raise ValueError("response certificate does not match the signing request")
    public_key = Path(args.public_key)
    with public_key.open("wb") as output:
        subprocess.run(
            crypto_command(args.openssl, ["x509", "-in", bound_path(args.openssl, args.certificate), "-pubkey", "-noout"]),
            check=True,
            env=crypto_env(args.openssl),
            stdout=output,
        )
    subprocess.run(
        crypto_command(args.openssl, [
            "dgst",
            "-sha256",
            "-verify",
            bound_path(args.openssl, args.public_key),
            "-signature",
            bound_path(args.openssl, args.signature),
            bound_path(args.openssl, args.response),
        ]),
        check=True,
        env=crypto_env(args.openssl),
    )
    shutil.copyfile(args.signed_uki, args.output)
    write_json(
        args.metadata,
        {
            **response_document,
            "certificate_sha256": actual_certificate,
            "signature_sha256": digest(args.signature),
            "verification": "openssl-dgst-sha256",
        },
    )


def test_key(args):
    subprocess.run(
        crypto_command(args.openssl, ["genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", bound_path(args.openssl, args.private_key)]),
        check=True,
        env=crypto_env(args.openssl),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        crypto_command(args.openssl, [
            "req",
            "-new",
            "-x509",
            "-key",
            bound_path(args.openssl, args.private_key),
            "-out",
            bound_path(args.openssl, args.certificate),
            "-days",
            "1",
            "-subj",
            "/CN=rules_mkosi ephemeral test key/",
        ]),
        check=True,
        env=crypto_env(args.openssl),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(required=True)
    request_parser = commands.add_parser("request")
    request_parser.add_argument("--openssl", required=True)
    request_parser.add_argument("--unsigned-uki", required=True)
    request_parser.add_argument("--certificate", required=True)
    request_parser.add_argument("--algorithm", default="rsa-pkcs1-sha256")
    request_parser.add_argument("--output", required=True)
    request_parser.set_defaults(function=request)

    key_parser = commands.add_parser("test-key")
    key_parser.add_argument("--openssl", required=True)
    key_parser.add_argument("--private-key", required=True)
    key_parser.add_argument("--certificate", required=True)
    key_parser.set_defaults(function=test_key)

    sign_parser = commands.add_parser("test-response")
    sign_parser.add_argument("--openssl", required=True)
    sign_parser.add_argument("--request", required=True)
    sign_parser.add_argument("--signed-uki", required=True)
    sign_parser.add_argument("--private-key", required=True)
    sign_parser.add_argument("--output", required=True)
    sign_parser.add_argument("--signature", required=True)
    sign_parser.set_defaults(function=test_response)

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--openssl", required=True)
    verify_parser.add_argument("--request", required=True)
    verify_parser.add_argument("--response", required=True)
    verify_parser.add_argument("--signed-uki", required=True)
    verify_parser.add_argument("--signature", required=True)
    verify_parser.add_argument("--certificate", required=True)
    verify_parser.add_argument("--public-key", required=True)
    verify_parser.add_argument("--output", required=True)
    verify_parser.add_argument("--metadata", required=True)
    verify_parser.set_defaults(function=verify)
    args = parser.parse_args()
    try:
        args.function(args)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        detail = error.stderr.decode(errors="replace") if isinstance(error, subprocess.CalledProcessError) and isinstance(error.stderr, bytes) else getattr(error, "stderr", None)
        raise SystemExit("SECURE_BOOT_RESPONSE_INVALID: {}".format(detail or error))


if __name__ == "__main__":
    main()
