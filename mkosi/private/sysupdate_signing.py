#!/usr/bin/python3
"""Offline OpenPGP signing of sysupdate payload manifests: requests, verified imports, and an ephemeral test signer.

rules_mkosi never handles the signing key. A request binds the exact SHA256SUMS of a payload to the fingerprint of the
expected public certificate; an external signer returns a detached signature, which the import verifies with sqv.
"""

import argparse
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import time
from pathlib import Path

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
openpgp = _load_sibling(__file__, "openpgp")
run_tool = _load_sibling(__file__, "launcher_tool").run_tool

FORMAT_VERSION = "mkosi-sysupdate-signing-request-v1"
CONTEXT = "systemd-sysupdate-sha256sums"
_MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([^/\s]+)")
_RSA_BITS = 3072
_RSA_EXPONENT = 65537


def manifest_files(manifest):
    """Returns the file digests of a SHA256SUMS manifest that sysupdate_payload wrote, keyed by file name."""
    files = {}
    for line in manifest.decode("ascii").splitlines():
        match = _MANIFEST_LINE.fullmatch(line)
        if not match or match[2] in files:
            raise ValueError("invalid SHA256SUMS line {!r}".format(line))
        files[match[2]] = match[1]
    if not files:
        raise ValueError("SHA256SUMS lists no files")
    return files


def create_request(args):
    """Writes the manifest, the normalized public certificate and the request that binds them."""
    manifest = (Path(args.payload) / "SHA256SUMS").read_bytes()
    files = manifest_files(manifest)
    certificate, fingerprint = openpgp.certificate(Path(args.public_key).read_bytes())
    request = {
        "context": CONTEXT,
        "files": files,
        "format_version": FORMAT_VERSION,
        "manifest": "SHA256SUMS",
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "signature": "SHA256SUMS.gpg",
        "signature_format": "openpgp-detached",
        "signer_fingerprint": fingerprint,
    }
    Path(args.manifest_output).write_bytes(manifest)
    Path(args.public_key_output).write_bytes(certificate)
    Path(args.output).write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _scratch(name):
    """Returns a new private directory below the working directory, which the Debian tools launcher binds."""
    scratch = Path(".{}-{}".format(name, os.getpid()))
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(mode=0o700)
    return scratch


def _sqv_error(sqv, certificate, signature, manifest):
    """Returns None if sqv verifies signature over manifest with certificate, else its error message."""
    scratch = _scratch("sysupdate-sqv")
    try:
        for name, data in (("certificate.pgp", certificate), ("SHA256SUMS.gpg", signature), ("SHA256SUMS", manifest)):
            (scratch / name).write_bytes(data)
        run_tool(
            sqv,
            "/usr/bin/sqv",
            "--keyring",
            scratch / "certificate.pgp",
            "--signature-file",
            scratch / "SHA256SUMS.gpg",
            scratch / "SHA256SUMS",
            capture=True,
        )
        return None
    except subprocess.CalledProcessError as error:
        return (error.stderr or b"").decode(errors="replace").strip() or "sqv failed"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _checked_request(args):
    """Returns the request, manifest and certificate after checking that they belong together."""
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    if request.get("format_version") != FORMAT_VERSION or request.get("context") != CONTEXT:
        raise ValueError("unsupported signing request")
    manifest = Path(args.manifest).read_bytes()
    if hashlib.sha256(manifest).hexdigest() != request["manifest_sha256"]:
        raise ValueError("SHA256SUMS does not match the signing request")
    certificate, fingerprint = openpgp.certificate(Path(args.public_key).read_bytes())
    if fingerprint != request["signer_fingerprint"]:
        raise ValueError(
            "public key {} is not the requested signer {}".format(fingerprint, request["signer_fingerprint"])
        )
    return request, manifest, certificate


def verify(args):
    """Writes the first candidate that is a valid detached signature of the requested manifest by the requested key."""
    request, manifest, certificate = _checked_request(args)
    errors = []
    for candidate in args.signature:
        try:
            signature = openpgp.detached_signature(Path(candidate).read_bytes())
        except ValueError as error:
            errors.append("{}: {}".format(Path(candidate).name, error))
            continue
        failure = _sqv_error(args.sqv, certificate, signature, manifest)
        if failure is None:
            Path(args.output).write_bytes(signature)
            return
        errors.append("{}: {}".format(Path(candidate).name, failure))
    raise ValueError(
        "no signature verifies SHA256SUMS {} with key {}: {}".format(
            request["manifest_sha256"], request["signer_fingerprint"], "; ".join(errors)
        )
    )


def _rsa_signer(openssl, scratch, key):
    """Returns a function that PKCS #1 v1.5-signs a SHA-256 digest with key and returns the signature as an integer."""

    def sign(digest):
        (scratch / "digest").write_bytes(digest)
        run_tool(
            openssl,
            "/usr/bin/openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            key,
            "-pkeyopt",
            "digest:sha256",
            "-in",
            scratch / "digest",
            "-out",
            scratch / "signature",
        )
        return int.from_bytes((scratch / "signature").read_bytes(), "big")

    return sign


def _new_rsa_key(openssl, key):
    """Generates an RSA key in key and returns its modulus."""
    run_tool(
        openssl,
        "/usr/bin/openssl",
        "genpkey",
        "-algorithm",
        "RSA",
        "-pkeyopt",
        "rsa_keygen_bits:{}".format(_RSA_BITS),
        "-pkeyopt",
        "rsa_keygen_pubexp:{}".format(_RSA_EXPONENT),
        "-out",
        key,
        # Hides the progress dots.
        capture=True,
    )
    output = run_tool(openssl, "/usr/bin/openssl", "rsa", "-in", key, "-noout", "-modulus", capture=True).stdout
    return int(output.decode("ascii").strip().removeprefix("Modulus="), 16)


def _write_certificate(args, public_key, sign, created):
    user_id = b"rules_mkosi ephemeral sysupdate test signer"
    certification = openpgp.rsa_sha256_signature(
        public_key, 0x13, created, openpgp.user_id_certification_data(public_key, user_id), sign, key_flags=0x03
    )
    certificate = (
        openpgp.packet(openpgp.TAG_PUBLIC_KEY, public_key)
        + openpgp.packet(openpgp.TAG_USER_ID, user_id)
        + openpgp.packet(openpgp.TAG_SIGNATURE, certification)
    )
    Path(args.public_key).write_bytes(certificate)
    keyring = Path(args.keyring_dir)
    keyring.mkdir(parents=True, exist_ok=True)
    (keyring / "import-pubring.gpg").write_bytes(certificate)


def _remove_private(scratch, key):
    """Overwrites the private key and removes the scratch directory that holds it."""
    if key.exists():
        key.write_bytes(bytes(key.stat().st_size))
    shutil.rmtree(scratch, ignore_errors=True)


def ephemeral_fixture(args):
    """Signs the SHA256SUMS of payloads with a new RSA key and writes its certificate.

    The private key stays in the scratch directory, which is overwritten and removed before returning.
    """
    scratch = Path(args.scratch)
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(mode=0o700, parents=True)
    key = scratch / "private-key.pem"
    try:
        # Backdated, so that a guest whose clock runs slightly behind accepts the key and its signatures.
        created = int(time.time()) - 3600
        public_key = openpgp.rsa_public_key(_new_rsa_key(args.openssl, key), _RSA_EXPONENT, created)
        sign = _rsa_signer(args.openssl, scratch, key)
        _write_certificate(args, public_key, sign, created)
        for payload, output in args.sign:
            manifest = (Path(payload) / "SHA256SUMS").read_bytes()
            signature = openpgp.rsa_sha256_signature(public_key, 0x00, created, manifest, sign)
            Path(output).write_bytes(openpgp.packet(openpgp.TAG_SIGNATURE, signature))
    finally:
        _remove_private(scratch, key)


_COMMANDS = {
    "request": (create_request, ("payload", "public-key", "manifest-output", "public-key-output", "output")),
    "verify": (verify, ("sqv", "request", "manifest", "public-key", "output")),
    "ephemeral-fixture": (ephemeral_fixture, ("openssl", "public-key", "keyring-dir", "scratch")),
}


def _parser():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(required=True)
    for command, (function, options) in _COMMANDS.items():
        subparser = commands.add_parser(command)
        for option in options:
            subparser.add_argument("--" + option, required=True)
        subparser.set_defaults(function=function)
    commands.choices["verify"].add_argument("--signature", action="append", required=True)
    commands.choices["ephemeral-fixture"].add_argument(
        "--sign", nargs=2, action="append", required=True, metavar=("PAYLOAD", "SIGNATURE")
    )
    return parser


def main():
    args = _parser().parse_args()
    try:
        args.function(args)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace") if error.stderr else str(error)
        raise SystemExit("SYSUPDATE_SIGNING_INVALID: " + detail) from error
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit("SYSUPDATE_SIGNING_INVALID: {}".format(error)) from error


if __name__ == "__main__":
    main()
