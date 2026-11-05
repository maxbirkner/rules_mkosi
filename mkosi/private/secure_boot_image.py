#!/usr/bin/python3
"""Writes a disk image whose ESP holds verified signed boot binaries and Secure Boot auto-enrollment keys.

The unsigned image is copied sparsely, and only its EFI system partition is rewritten in place with the pinned mtools:
every ESP file whose bytes equal a signing request's unsigned binary is replaced by the verified signed binary, the
auto-enrollment .auth files are added to /loader/keys/auto/ and loader.conf gets secure-boot-enroll. The GPT, the
other partitions, and the file system's identity and geometry stay unchanged, so the result is deterministic for the
same signed inputs.
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

FORMAT = "mkosi-secure-boot-signed-image-v1"
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


def _assign(tree, replacements):
    """Records the ESP paths of each replacement; fails if one is unused or an unsigned PE binary would remain."""
    unsigned = []
    for esp_path in esp_files.tree_files(tree):
        data = (tree / esp_path).read_bytes()
        replacement = replacements.get(_sha256(data))
        if replacement:
            replacement["paths"].append(esp_path)
        elif _is_unsigned_pe(data):
            unsigned.append(esp_path)
    unused = sorted(replacement["name"] for replacement in replacements.values() if not replacement["paths"])
    if unused:
        raise ValueError("the ESP holds no unsigned copy of the signed binaries for {}".format(", ".join(unused)))
    if unsigned:
        raise ValueError(
            "the ESP would keep unsigned PE/COFF binaries that Secure Boot firmware refuses to load: {}; sign them "
            "with secure_boot_signing_request(esp_path = ...)".format(", ".join(unsigned))
        )


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


def _check_db_trusts(args, scratch, db_lists, replacements):
    """Fails unless db holds, or holds an issuer of, the certificate of every signed binary."""
    trusted = efi_auth.x509_certificates(db_lists)
    bundle = scratch / "db.pem"
    bundle.write_bytes(b"".join(secure_boot.certificate_pem(certificate) for certificate in trusted))
    for replacement in replacements.values():
        if replacement["certificate"] in trusted:
            continue
        signer = scratch / "signer.pem"
        signer.write_bytes(secure_boot.certificate_pem(replacement["certificate"]))
        try:
            launcher_tool.run_tool(
                args.tools,
                "/usr/bin/openssl",
                "verify",
                "-partial_chain",
                "-no_check_time",
                "-CAfile",
                bundle,
                signer,
                capture=True,
            )
        except subprocess.CalledProcessError as error:
            raise ValueError(
                "db.auth does not trust the certificate that signed {}; enrolling it would make the device refuse "
                "to boot".format(", ".join(replacement["paths"]))
            ) from error


def _find(tree_paths, esp_path):
    """Returns the existing path that a case-insensitive FAT lookup of esp_path finds, or None."""
    return next((path for path in tree_paths if path.lower() == esp_path.lower()), None)


def _loader_conf(tree, mode):
    """Returns the ESP path and content of loader.conf with exactly one secure-boot-enroll line."""
    existing = _find(esp_files.tree_files(tree), _LOADER_CONF)
    lines = (tree / existing).read_text(encoding="utf-8").splitlines() if existing else []
    kept = [line for line in lines if line.split()[:1] != ["secure-boot-enroll"]]
    return existing or _LOADER_CONF, "\n".join([*kept, "secure-boot-enroll " + mode]) + "\n"


def _changes(args, scratch, tree, replacements):
    """Returns the new ESP files as {ESP path: source file} after validating every input."""
    changes = {}
    for replacement in replacements.values():
        for esp_path in replacement["paths"]:
            changes[esp_path] = replacement["signed"]
    if not args.auto_enroll_key:
        return changes
    keys = _enrollment_keys(args.auto_enroll_key)
    _check_db_trusts(args, scratch, keys["db"][1], replacements)
    for name, (path, _) in sorted(keys.items()):
        changes[_KEYS + "/" + name + ".auth"] = path
    esp_path, content = _loader_conf(tree, args.secure_boot_enroll)
    loader_conf = scratch / "loader.conf"
    loader_conf.write_text(content, encoding="utf-8")
    changes[esp_path] = loader_conf
    return changes


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


def _metadata(args, replacements, changes):
    keys = {Path(path).stem: _sha256(Path(path).read_bytes()) for path in args.auto_enroll_key or []}
    replaced = [
        {"esp_path": esp_path, "signed_sha256": _sha256(replacement["signed"].read_bytes()), "unsigned_sha256": digest}
        for digest, replacement in sorted(replacements.items())
        for esp_path in replacement["paths"]
    ]
    return {
        "auto_enroll_keys": keys,
        "changed_esp_paths": sorted(changes),
        "format_version": FORMAT,
        "replaced": sorted(replaced, key=lambda entry: entry["esp_path"]),
        "secure_boot_enroll": args.secure_boot_enroll if keys else None,
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
        _assign(tree, replacements)
        changes = _changes(args, scratch, tree, replacements)
        _apply(args, scratch, esp_image, tree, changes)
        _verify(scratch, changes)
        Path(args.output).unlink(missing_ok=True)
        esp_files.copy_range(args.image, args.output, 0, os.path.getsize(args.image))
        esp_files.copy_range(esp_image, args.output, 0, esp_image.stat().st_size, offset, sparse=False)
        Path(args.metadata).write_text(
            json.dumps(_metadata(args, replacements, changes), indent=2, sort_keys=True) + "\n"
        )
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
