#!/usr/bin/python3
"""Writes a disk image whose ESP holds verified signed boot binaries and Secure Boot auto-enrollment keys.

The unsigned image is copied sparsely, and only its EFI system partition is rewritten in place with the pinned mtools:
every ESP file whose bytes equal a signing request's unsigned binary is replaced by the verified signed binary, the
auto-enrollment .auth files are added to /loader/keys/auto/, loader.conf gets secure-boot-enroll, and a JSON manifest
of the signed binaries and keys is written to /loader/rules_mkosi-secure-boot.json. The GPT, the other partitions, and
the file system's identity and geometry stay unchanged, so the result is deterministic for the same signed inputs.
"""

import argparse
import hashlib
import json
import os
import runpy
import shlex
import shutil
import struct
import subprocess
from pathlib import Path

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
efi_auth = _load_sibling(__file__, "efi_auth")
esp_files = _load_sibling(__file__, "esp_files")
launcher_tool = _load_sibling(__file__, "launcher_tool")
secure_boot = _load_sibling(__file__, "secure_boot")

FORMAT = "mkosi-secure-boot-signed-image-v2"
ESP_MANIFEST_FORMAT = "mkosi-secure-boot-esp-manifest-v1"
# systemd-boot reads only fixed names below /loader/, such as loader.conf, entries/ and keys/<name>/<variable>.auth,
# so it ignores this file.
ESP_MANIFEST = "loader/rules_mkosi-secure-boot.json"
_LOADER_CONF = "loader/loader.conf"
_KEYS = "loader/keys/auto"
# Earliest FAT timestamp; used when the ESP holds no file to take a timestamp from.
_FAT_EPOCH = 315532800


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _replacements(signed_arguments):
    """Returns the signed binaries keyed by the SHA-256 of the unsigned binary that their request names."""
    replacements = {}
    for signed, request, certificate in signed_arguments:
        document = json.loads(Path(request).read_text(encoding="utf-8"))
        digest = document["unsigned_sha256"]
        if digest in replacements:
            raise ValueError("two signed binaries replace the same unsigned binary {}".format(digest))
        replacements[digest] = {
            "certificate": secure_boot.certificate_der(certificate),
            "name": document["esp_path"] or "the UKI",
            "paths": [],
            "signed": Path(signed),
        }
    return replacements


def _is_unsigned_pe(data):
    try:
        secure_boot.parse_pe(data, False)
    except (ValueError, struct.error):
        return False
    return True


def _entry_binaries(text):
    """Returns the lowercase ESP paths of the linux and efi keys of a boot loader entry.

    Like systemd-boot, splits each line at the first space or tab and strips one pair of surrounding double quotes.
    """
    paths = []
    for line in text.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and fields[0] in ("linux", "efi"):
            value = fields[1].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            paths.append(value.replace("\\", "/").lstrip("/").lower())
    return paths


def _startable(tree, esp_paths):
    """Returns the esp_paths that the firmware or systemd-boot can start.

    Those are *.efi files, which the firmware's boot options and systemd-boot's discovery name, and the linux and efi
    files of boot loader entries. Other files, such as a kernel that kernel-install left on the ESP, are never started.
    """
    referenced = set()
    for esp_path in esp_files.tree_files(tree):
        if esp_path.lower().startswith("loader/entries/") and esp_path.lower().endswith(".conf"):
            referenced.update(_entry_binaries((tree / esp_path).read_text(encoding="utf-8", errors="replace")))
    return [path for path in esp_paths if path.lower().endswith(".efi") or path.lower() in referenced]


def _assign(tree, replacements):
    """Records the ESP paths of each replacement and returns the startable, already signed, PE binaries.

    Fails if a replacement is unused or an unsigned PE binary would remain.
    """
    unsigned = []
    signed = []
    for esp_path in esp_files.tree_files(tree):
        data = (tree / esp_path).read_bytes()
        replacement = replacements.get(_sha256(data))
        if replacement:
            replacement["paths"].append(esp_path)
        elif secure_boot.is_pe(data):
            (unsigned if _is_unsigned_pe(data) else signed).append(esp_path)
    unused = sorted(replacement["name"] for replacement in replacements.values() if not replacement["paths"])
    if unused:
        raise ValueError("the ESP holds no unsigned copy of the signed binaries for {}".format(", ".join(unused)))
    if unsigned:
        raise ValueError(
            "the ESP would keep unsigned PE/COFF binaries that Secure Boot firmware refuses to load: {}; sign them "
            "with secure_boot_signing_request(esp_path = ...)".format(", ".join(unsigned))
        )
    return _startable(tree, signed)


def _enrollment_keys(paths):
    """Returns the validated .auth files keyed by variable name with their signature lists."""
    keys = {}
    for path in map(Path, paths):
        if path.suffix != ".auth" or path.stem in keys:
            raise ValueError("auto-enrollment files must be distinct <variable>.auth files, got {}".format(path.name))
        try:
            _, lists = efi_auth.parse_auth(path.stem, path.read_bytes())
        except (ValueError, struct.error) as error:
            raise ValueError("{}: {}".format(path.name, error)) from error
        keys[path.stem] = (path, lists)
    missing = [name + ".auth" for name in efi_auth.REQUIRED if name not in keys]
    if missing:
        raise ValueError("auto-enrollment needs {}".format(", ".join(missing)))
    return keys


def describe_keys(keys):
    """Returns the records of the validated .auth files of _enrollment_keys, in PK, KEK, db, dbx order.

    Each record holds the file's ESP path, SHA-256 and size, and the SHA-256 fingerprints of the DER X.509
    certificates in its signature lists, which install tooling compares with the certificates that a device trusts.
    """
    records = []
    for name in (name for name in efi_auth.VARIABLES if name in keys):
        path, lists = keys[name]
        data = path.read_bytes()
        records.append(
            {
                "esp_path": "{}/{}.auth".format(_KEYS, name),
                "sha256": _sha256(data),
                "signature_count": sum(len(entries) for _, entries in lists),
                "size": len(data),
                "variable": name,
                "x509_sha256": [_sha256(certificate) for certificate in efi_auth.x509_certificates(lists)],
            }
        )
    return records


def describe_replacements(replacements):
    """Returns the ESP paths of the signed binaries with their digests and signer certificate fingerprint."""
    replaced = [
        {
            "esp_path": esp_path,
            "signed_sha256": _sha256(replacement["signed"].read_bytes()),
            "signer_sha256": _sha256(replacement["certificate"]),
            "unsigned_sha256": digest,
        }
        for digest, replacement in replacements.items()
        for esp_path in replacement["paths"]
    ]
    return sorted(replaced, key=lambda entry: entry["esp_path"])


def build_esp_manifest(replacements, keys, mode):
    """Returns the manifest that the ESP holds at ESP_MANIFEST, for tools that inspect a written image."""
    return {
        "auto_enroll_keys": describe_keys(keys),
        "format_version": ESP_MANIFEST_FORMAT,
        "replaced": describe_replacements(replacements),
        "secure_boot_enroll": mode if keys else None,
    }


def _dump_json(document):
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _db_trusts(args, bundle, signer, chain=None):
    """Returns whether the db certificates in bundle trust signer, through the intermediate certificates in chain."""
    intermediates = ["-untrusted", chain] if chain else []
    try:
        launcher_tool.run_tool(
            args.tools,
            "/usr/bin/openssl",
            "verify",
            "-partial_chain",
            "-no_check_time",
            "-CAfile",
            bundle,
            *intermediates,
            signer,
            capture=True,
        )
    except subprocess.CalledProcessError:
        return False
    return True


def _embedded_signer(args, scratch, tree, esp_path):
    """Returns the files of the verified signer and of all certificates of the Authenticode signature of esp_path."""
    try:
        payload = secure_boot.embedded_authenticode((tree / esp_path).read_bytes())
    except (ValueError, struct.error) as error:
        raise ValueError("cannot read the Authenticode signature of {}: {}".format(esp_path, error)) from error
    pkcs7, signer, chain = scratch / "embedded.p7", scratch / "embedded-signer.pem", scratch / "embedded-chain.pem"
    pkcs7.write_bytes(payload)
    content = scratch / "embedded-content.bin"
    verify = ["smime", "-verify", "-inform", "DER", "-in", pkcs7, "-noverify", "-signer", signer, "-out", content]
    certificates = ["pkcs7", "-inform", "DER", "-in", pkcs7, "-print_certs", "-out", chain]
    try:
        launcher_tool.run_tool(args.tools, "/usr/bin/openssl", *verify, capture=True)
        launcher_tool.run_tool(args.tools, "/usr/bin/openssl", *certificates, capture=True)
    except subprocess.CalledProcessError as error:
        raise ValueError("the Authenticode signature of {} does not verify".format(esp_path)) from error
    return signer, chain if chain.stat().st_size else None


def _untrusted(paths):
    return ValueError(
        "db.auth does not trust the certificate that signed {}; enrolling it would make the device refuse to "
        "boot".format(", ".join(paths))
    )


def _check_db_trusts(args, scratch, db_lists, replacements, tree, presigned):
    """Fails unless db holds, or holds an issuer of, the signer of every signed binary on the ESP.

    That covers the imported signed binaries and the already signed binaries, such as a distribution-signed boot loader.
    """
    trusted = efi_auth.x509_certificates(db_lists)
    bundle = scratch / "db.pem"
    bundle.write_bytes(b"".join(secure_boot.certificate_pem(certificate) for certificate in trusted))
    for replacement in replacements.values():
        signer = scratch / "signer.pem"
        signer.write_bytes(secure_boot.certificate_pem(replacement["certificate"]))
        if replacement["certificate"] not in trusted and not _db_trusts(args, bundle, signer):
            raise _untrusted(replacement["paths"])
    for esp_path in presigned:
        if not _db_trusts(args, bundle, *_embedded_signer(args, scratch, tree, esp_path)):
            raise _untrusted([esp_path])


def _find(tree_paths, esp_path):
    """Returns the existing path that a case-insensitive FAT lookup of esp_path finds, or None."""
    return next((path for path in tree_paths if path.lower() == esp_path.lower()), None)


def _loader_conf(tree, mode):
    """Returns the ESP path and content of loader.conf with exactly one secure-boot-enroll line."""
    existing = _find(esp_files.tree_files(tree), _LOADER_CONF)
    lines = (tree / existing).read_text(encoding="utf-8").splitlines() if existing else []
    kept = [line for line in lines if line.split()[:1] != ["secure-boot-enroll"]]
    return existing or _LOADER_CONF, "\n".join([*kept, "secure-boot-enroll " + mode]) + "\n"


def _changes(args, scratch, tree, replacements, presigned):
    """Returns the new ESP files as {ESP path: source file} and the ESP manifest after validating every input."""
    changes = {}
    for replacement in replacements.values():
        for esp_path in replacement["paths"]:
            changes[esp_path] = replacement["signed"]
    keys = {}
    if args.auto_enroll_key:
        keys = _enrollment_keys(args.auto_enroll_key)
        _check_db_trusts(args, scratch, keys["db"][1], replacements, tree, presigned)
        for name, (path, _) in sorted(keys.items()):
            changes[_KEYS + "/" + name + ".auth"] = path
        esp_path, content = _loader_conf(tree, args.secure_boot_enroll)
        loader_conf = scratch / "loader.conf"
        loader_conf.write_text(content, encoding="utf-8")
        changes[esp_path] = loader_conf
    manifest = build_esp_manifest(replacements, keys, args.secure_boot_enroll)
    manifest_file = scratch / "manifest.json"
    manifest_file.write_text(_dump_json(manifest), encoding="utf-8")
    changes[_find(esp_files.tree_files(tree), ESP_MANIFEST) or ESP_MANIFEST] = manifest_file
    return changes, manifest


def _missing_directories(tree, changes):
    """Returns the ESP directories that the changed files need and the ESP lacks, parents first."""
    existing = {str(path.relative_to(tree)).lower() for path in tree.rglob("*") if path.is_dir()}
    needed = {str(parent) for esp_path in changes for parent in Path(esp_path).parents if str(parent) != "."}
    return sorted((directory for directory in needed if directory.lower() not in existing), key=len)


def _apply(args, scratch, esp_image, tree, changes):
    """Copies the changes into esp_image with stable timestamps and copies the result to scratch/verify."""
    timestamps = [int((tree / path).stat().st_mtime) for path in esp_files.tree_files(tree)]
    epoch = max(timestamps, default=_FAT_EPOCH)
    stage = scratch / "stage"
    stage.mkdir()
    image = shlex.quote(launcher_tool.namespace_path(args.tools, esp_image))
    lines = [
        "/usr/bin/mmd -i {} {}".format(image, shlex.quote("::/" + directory))
        for directory in _missing_directories(tree, changes)
    ]
    for index, (esp_path, source) in enumerate(sorted(changes.items())):
        staged = stage / str(index)
        shutil.copyfile(source, staged)
        os.utime(staged, (epoch, epoch))
        staged_path = launcher_tool.namespace_path(args.tools, staged)
        lines.append("/usr/bin/mcopy -o -m -i {} {} {}".format(image, staged_path, shlex.quote("::/" + esp_path)))
    lines.append(esp_files.copy_tree_command(args.tools, esp_image, scratch / "verify"))
    esp_files.run_script(args.tools, scratch, lines, {"SOURCE_DATE_EPOCH": str(epoch), "TZ": "UTC"})


def _verify(scratch, changes):
    """Fails unless every changed ESP file now holds its source's bytes."""
    verify = scratch / "verify"
    files = esp_files.tree_files(verify)
    for esp_path, source in changes.items():
        found = _find(files, esp_path)
        if found is None or (verify / found).read_bytes() != Path(source).read_bytes():
            raise ValueError("the rewritten ESP does not hold {}".format(esp_path))


def _metadata(manifest, changes):
    """Returns the record of the build: the ESP manifest's fields with the changed ESP paths."""
    return manifest | {
        "changed_esp_paths": sorted(changes),
        "esp_manifest": _find(sorted(changes), ESP_MANIFEST),
        "format_version": FORMAT,
    }


def sign_image(args):
    scratch = Path(args.scratch)
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(mode=0o700, parents=True)
    try:
        replacements = _replacements(args.signed)
        esp_image = scratch / "esp.img"
        offset = esp_files.extract_esp(args.image, args.partition_metadata, esp_image)
        tree = scratch / "tree"
        esp_files.run_script(
            args.tools, scratch, [esp_files.copy_tree_command(args.tools, esp_image, tree)], {"TZ": "UTC"}
        )
        presigned = _assign(tree, replacements)
        changes, manifest = _changes(args, scratch, tree, replacements, presigned)
        _apply(args, scratch, esp_image, tree, changes)
        _verify(scratch, changes)
        Path(args.output).unlink(missing_ok=True)
        esp_files.copy_range(args.image, args.output, 0, os.path.getsize(args.image))
        esp_files.copy_range(esp_image, args.output, 0, esp_image.stat().st_size, offset, sparse=False)
        Path(args.metadata).write_text(_dump_json(_metadata(manifest, changes)))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tools", "image", "partition-metadata", "scratch", "output", "metadata"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--signed", nargs=3, action="append", required=True, metavar=("SIGNED", "REQUEST", "CERT"))
    parser.add_argument("--auto-enroll-key", action="append")
    parser.add_argument("--secure-boot-enroll", choices=("manual", "if-safe", "force"), default="if-safe")
    secure_boot.report_errors(sign_image, parser.parse_args())


if __name__ == "__main__":
    main()
