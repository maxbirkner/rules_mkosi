"""Stage a deterministic, authenticated Debian APT snapshot tree."""

import argparse
import hashlib
import lzma
import os
import pathlib
import shutil
import subprocess
import sys
import re


def _digest(path):
    with open(path, "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _verify_digest(path, expected, description):
    actual = _digest(path)
    if actual != expected:
        raise ValueError(
            "%s digest mismatch: expected=%s actual=%s" % (description, expected, actual)
        )


def _verify_package(path, expected_digest, expected_size, description):
    _verify_digest(path, expected_digest, description)
    actual_size = os.stat(path).st_size
    if actual_size != expected_size:
        raise ValueError(
            "%s size mismatch: expected=%d actual=%d"
            % (description, expected_size, actual_size)
        )


def _paragraphs(data):
    paragraphs = []
    current = {}
    field = None
    for line in data.decode("utf-8").splitlines():
        if not line:
            if current:
                paragraphs.append(current)
                current = {}
                field = None
            continue
        if line[0].isspace():
            if field is None:
                raise ValueError("continuation without a Debian metadata field")
            current[field] += "\n" + line
            continue
        if ":" not in line:
            raise ValueError("malformed Debian metadata field")
        field, value = line.split(":", 1)
        if field in current:
            raise ValueError("duplicate Debian metadata field: %s" % field)
        current[field] = value.lstrip()
    if current:
        paragraphs.append(current)
    return paragraphs


def _sha256_entries(release):
    """Yields (digest, size, path) of every entry in the SHA256 field of a Release file."""
    in_sha256 = False
    seen = set()
    for line in release.decode("utf-8").splitlines():
        if not line:
            continue
        if not line[0].isspace() and line.endswith(":"):
            in_sha256 = line == "SHA256:"
            continue
        if not in_sha256:
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError("malformed SHA256 checksum entry")
        digest, size, entry_path = fields
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("malformed SHA256 checksum digest")
        if not size.isdigit():
            raise ValueError("malformed SHA256 checksum size")
        if entry_path in seen:
            raise ValueError("duplicate SHA256 checksum entry")
        seen.add(entry_path)
        yield digest, int(size), entry_path


def _release_hash(release, relative_path, expected_size, expected_digest):
    path = relative_path
    if path.startswith("dists/"):
        path = path.split("/", 2)[2]
    matches = [(digest, size) for digest, size, entry_path in _sha256_entries(release) if entry_path == path]
    if len(matches) != 1:
        raise ValueError("Packages metadata must have exactly one SHA256 entry")
    digest, size = matches[0]
    if size != expected_size:
        raise ValueError("Release metadata size disagrees with the lock")
    if digest.lower() != expected_digest.lower():
        raise ValueError("Release metadata digest disagrees with the lock")


_SQV_KEYRING = "--keyring=/usr/share/keyrings/debian-archive-keyring.gpg"


def _run_sqv(launcher, binds, sqv_arguments, environment, scratch, description):
    """Runs sqv from the Debian tools tree with the pinned archive keyring and the given namespace binds."""
    command = [launcher]
    for option, source, destination in binds:
        command += [option, source + ":" + destination]
    command += ["/usr/bin/sqv", _SQV_KEYRING] + sqv_arguments
    result = subprocess.run(
        command,
        env=dict(environment, MKOSI_DEBIAN_TOOLS_SCRATCH=scratch),
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(
            "Debian %s signature verification failed: %s"
            % (description, result.stderr.decode("utf-8", "replace").strip())
        )


def _verify_signature(launcher, inrelease, release, release_gpg, output, scratch):
    scratch = os.path.abspath(scratch)
    environment = {"PATH": ""}
    for variable in ("RUNFILES_DIR", "RUNFILES_MANIFEST_FILE", "RUNFILES_MANIFEST_ONLY"):
        if variable in os.environ:
            environment[variable] = os.environ[variable]
    _run_sqv(
        launcher,
        (
            ("--ro-bind", os.path.abspath(inrelease), "/inputs/InRelease"),
            ("--rw-bind", os.path.abspath(output), "/outputs/repository"),
        ),
        ["--output=/outputs/repository/verified-release", "--cleartext", "/inputs/InRelease"],
        environment,
        scratch + "/inrelease",
        "InRelease",
    )
    _run_sqv(
        launcher,
        (
            ("--ro-bind", os.path.abspath(release), "/inputs/Release"),
            ("--ro-bind", os.path.abspath(release_gpg), "/inputs/Release.gpg"),
        ),
        ["--signature-file=/inputs/Release.gpg", "/inputs/Release"],
        environment,
        scratch + "/release",
        "Release",
    )


def _copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o644)


def _safe_package_path(filename):
    relative = pathlib.PurePosixPath(filename)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or str(relative) != filename
        or not str(relative).startswith("pool/")
    ):
        raise ValueError("unsafe package path: %s" % filename)
    return relative


def _decompress(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with lzma.open(source, "rb") as compressed, open(destination, "wb") as output:
        shutil.copyfileobj(compressed, output)
    os.chmod(destination, 0o644)


def _set_deterministic_metadata(root):
    for directory, dirnames, names in os.walk(root, topdown=False):
        for name in names:
            path = os.path.join(directory, name)
            if not os.path.islink(path):
                os.chmod(path, 0o644)
            os.utime(path, (0, 0), follow_symlinks=False)
        for name in dirnames:
            path = os.path.join(directory, name)
            if not os.path.islink(path):
                os.chmod(path, 0o755)
            os.utime(path, (0, 0), follow_symlinks=False)
        os.chmod(directory, 0o755)
        os.utime(directory, (0, 0), follow_symlinks=False)
    os.utime(root, (0, 0), follow_symlinks=False)


def _read_package_metadata(indexes, expected):
    actual = {}
    for package_index, index_architecture in indexes:
        with open(package_index, "rb") as source:
            for paragraph in _paragraphs(source.read()):
                architecture = paragraph.get("Architecture")
                if architecture not in ("amd64", "all"):
                    raise ValueError("unsupported package architecture")
                if index_architecture == "all" and architecture != "all":
                    raise ValueError("binary-all index contains non-all package")
                key = (
                    paragraph.get("Package"),
                    paragraph.get("Version"),
                    architecture,
                )
                fields = (
                    paragraph.get("Filename"),
                    paragraph.get("Size"),
                    paragraph.get("SHA256"),
                )
                if not fields[0] or not fields[1] or not fields[2] or not fields[1].isdigit():
                    raise ValueError("incomplete package metadata")
                record = (fields[0], int(fields[1]), fields[2])
                if key in actual and actual[key] != record:
                    raise ValueError("conflicting duplicate package metadata: %s" % paragraph.get("Package"))
                if key in expected:
                    actual[key] = record
    return actual


def _authenticated_release_matches(payload, release):
    return payload == release or payload + b"\n" == release


def _component_indexes(args):
    if len(args.component_indexes) != len(args.component_index_files):
        raise ValueError("--component-index and --component-index-file counts differ")
    indexes = [
        ("main", "amd64", args.packages_path, args.packages_xz_sha256, args.packages_xz),
        ("main", "all", args.packages_all_path, args.packages_all_xz_sha256, args.packages_all_xz),
    ]
    for record, path in zip(args.component_indexes, args.component_index_files):
        fields = record.split("|")
        if len(fields) != 4:
            raise ValueError("component index record must have four fields")
        component, architecture, relative, digest = fields
        indexes.append((component, architecture, relative, digest, path))
    seen = set()
    for component, architecture, relative, _, _ in indexes:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", component):
            raise ValueError("invalid Debian component: %s" % component)
        if architecture not in ("amd64", "all"):
            raise ValueError("unsupported index architecture: %s" % architecture)
        expected = "dists/%s/%s/binary-%s/Packages.xz" % (args.codename, component, architecture)
        if relative != expected:
            raise ValueError("Packages index %s must be staged at %s" % (relative, expected))
        if (component, architecture) in seen:
            raise ValueError("duplicate Packages index: %s %s" % (component, architecture))
        seen.add((component, architecture))
    components = {component for component, _, _, _, _ in indexes}
    if seen != {(component, architecture) for component in components for architecture in ("amd64", "all")}:
        raise ValueError("every Debian component needs binary-amd64 and binary-all indexes")
    return indexes


def _verify_input_digests(args, indexes):
    _verify_digest(args.inrelease, args.inrelease_sha256, "InRelease")
    _verify_digest(args.release, args.release_sha256, "Release")
    _verify_digest(args.release_gpg, args.release_gpg_sha256, "Release.gpg")
    for component, architecture, _, digest, path in indexes:
        _verify_digest(path, digest, "Packages %s/%s" % (component, architecture))


def _verify_authenticated_release(verified, release, indexes):
    """Checks that the signature-verified InRelease payload is the locked Release and lists every index."""
    authenticated_release = verified.read_bytes()
    if not _authenticated_release_matches(authenticated_release, pathlib.Path(release).read_bytes()):
        raise ValueError("authenticated InRelease does not match locked Release")
    for _, _, relative, digest, path in indexes:
        _release_hash(authenticated_release, relative, len(pathlib.Path(path).read_bytes()), digest)


def _stage_release_files(args, indexes, destination):
    """Copies the release files and decompresses every Packages index; returns the staged indexes."""
    dists = destination / "dists" / args.codename
    _copy(args.inrelease, dists / "InRelease")
    _copy(args.release, dists / "Release")
    _copy(args.release_gpg, dists / "Release.gpg")
    staged_indexes = []
    for _, architecture, relative, _, path in indexes:
        staged = destination / relative[: -len(".xz")]
        _decompress(path, staged)
        staged_indexes.append((staged, architecture))
    return staged_indexes


def _locked_packages(package_records):
    """Returns (filename, size, digest, local name) of every locked package keyed by (name, version, arch)."""
    expected = {}
    filenames = set()
    local_names = set()
    for package in package_records:
        fields = package.split("|")
        if len(fields) != 7:
            raise ValueError("locked package record must have seven fields")
        name, version, architecture, filename, size, digest, local_name = fields
        if not size.isdigit():
            raise ValueError("locked package size is invalid")
        key = (name, version, architecture)
        filename = str(_safe_package_path(filename))
        if key in expected:
            raise ValueError("duplicate locked package: %s" % "|".join(key))
        if filename in filenames:
            raise ValueError("package path collision: %s" % filename)
        if local_name in local_names:
            raise ValueError("duplicate local package name: %s" % local_name)
        filenames.add(filename)
        local_names.add(local_name)
        expected[key] = (filename, int(size), digest, local_name)
    return expected


def _verify_package_metadata(staged_indexes, expected):
    actual = _read_package_metadata(staged_indexes, expected)
    if actual.keys() != expected.keys():
        raise ValueError("locked packages do not match Packages metadata")
    for key in sorted(expected):
        if actual[key] != expected[key][:3]:
            raise ValueError("package metadata disagrees with lock: %s" % key[0])


def _stage_packages(args, expected, destination):
    records_by_name = {value[3]: (key, value) for key, value in expected.items()}
    if set(records_by_name) != set(args.package_names):
        raise ValueError("package inputs do not match lock package names")
    for package, local_name in zip(args.packages, args.package_names):
        _, (remote_filename, expected_size, digest, _) = records_by_name[local_name]
        _verify_package(package, digest, expected_size, "package %s" % local_name)
        relative = _safe_package_path(remote_filename)
        _copy(package, destination / relative)


def stage(args):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.codename):
        raise ValueError("invalid Debian codename: %s" % args.codename)
    indexes = _component_indexes(args)
    _verify_input_digests(args, indexes)
    _verify_signature(
        args.launcher,
        args.inrelease,
        args.release,
        args.release_gpg,
        args.output,
        args.scratch,
    )
    destination = pathlib.Path(args.output)
    verified = destination / "verified-release"
    _verify_authenticated_release(verified, args.release, indexes)
    staged_indexes = _stage_release_files(args, indexes, destination)
    expected = _locked_packages(args.package_records)
    _verify_package_metadata(staged_indexes, expected)
    _stage_packages(args, expected, destination)
    verified.unlink()
    _set_deterministic_metadata(destination)


def _parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inrelease", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--release-gpg", required=True)
    parser.add_argument("--packages-xz", required=True)
    parser.add_argument("--packages-all-xz", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--launcher", required=True)
    parser.add_argument("--inrelease-sha256", required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--release-gpg-sha256", required=True)
    parser.add_argument("--packages-xz-sha256", required=True)
    parser.add_argument("--packages-all-xz-sha256", required=True)
    parser.add_argument("--packages-path", required=True)
    parser.add_argument("--packages-all-path", required=True)
    parser.add_argument("--codename", default="trixie")
    parser.add_argument("--component-index", dest="component_indexes", action="append", default=[])
    parser.add_argument(
        "--component-index-file",
        dest="component_index_files",
        action="append",
        default=[],
    )
    parser.add_argument("--package", dest="package_records", action="append", default=[])
    parser.add_argument("--package-file", dest="packages", action="append", default=[])
    parser.add_argument("--package-name", dest="package_names", action="append", default=[])
    return parser


def main():
    parser = _parser()
    args = parser.parse_args()
    if len(args.packages) != len(args.package_names):
        parser.error("--package-file and --package-name counts differ")
    try:
        stage(args)
    except (OSError, ValueError, lzma.LZMAError) as error:
        print("Debian snapshot staging failed: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
