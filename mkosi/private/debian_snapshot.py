"""Stage a deterministic, authenticated Debian APT snapshot tree."""

import argparse
import hashlib
import lzma
import os
import pathlib
import shutil
import subprocess
import sys


def _digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_digest(path, expected, description):
    actual = _digest(path)
    if actual != expected:
        raise ValueError(
            "%s digest mismatch: expected=%s actual=%s" % (description, expected, actual)
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


def _release_hash(release, relative_path, expected_size, expected_digest):
    if relative_path.startswith("dists/"):
        relative_path = relative_path.split("/", 2)[2]
    for line in release.decode("utf-8").splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1] == str(expected_size) and (
            fields[2] == relative_path or fields[2].endswith("/" + relative_path)
        ):
            if fields[0].lower() != expected_digest.lower():
                raise ValueError("Release metadata digest disagrees with the lock")
            return
    raise ValueError("Packages metadata is absent from the authenticated Release")


def _verify_signature(launcher, inrelease, release, release_gpg, output, scratch):
    inrelease = os.path.abspath(inrelease)
    release = os.path.abspath(release)
    release_gpg = os.path.abspath(release_gpg)
    output = os.path.abspath(output)
    scratch = os.path.abspath(scratch)
    cleartext_command = [
        launcher,
        "--ro-bind",
        inrelease + ":/inputs/InRelease",
        "--rw-bind",
        output + ":/outputs/repository",
        "/usr/bin/sqv",
        "--keyring=/usr/share/keyrings/debian-archive-keyring.gpg",
        "--output=/outputs/repository/verified-release",
        "--cleartext",
        "/inputs/InRelease",
    ]
    result = subprocess.run(
        cleartext_command,
        env={
            "PATH": "",
            "MKOSI_DEBIAN_TOOLS_SCRATCH": scratch + "/inrelease",
        },
    )
    if result.returncode:
        raise ValueError("Debian InRelease signature verification failed")
    detached_command = [
        launcher,
        "--ro-bind",
        release + ":/inputs/Release",
        "--ro-bind",
        release_gpg + ":/inputs/Release.gpg",
        "/usr/bin/sqv",
        "--keyring=/usr/share/keyrings/debian-archive-keyring.gpg",
        "--signature-file=/inputs/Release.gpg",
        "/inputs/Release",
    ]
    result = subprocess.run(
        detached_command,
        env={
            "PATH": "",
            "MKOSI_DEBIAN_TOOLS_SCRATCH": scratch + "/release",
        },
    )
    if result.returncode:
        raise ValueError("Debian Release signature verification failed")


def _copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o644)


def _safe_package_path(filename):
    relative = pathlib.PurePosixPath(filename)
    if relative.is_absolute() or ".." in relative.parts or not str(relative).startswith("pool/"):
        raise ValueError("unsafe package path: %s" % filename)
    return relative


def _decompress(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with lzma.open(source, "rb") as compressed, open(destination, "wb") as output:
        shutil.copyfileobj(compressed, output)


def _set_deterministic_metadata(root):
    for directory, dirnames, names in os.walk(root, topdown=False):
        for name in names + dirnames:
            os.utime(os.path.join(directory, name), (0, 0), follow_symlinks=False)
        os.utime(directory, (0, 0), follow_symlinks=False)
    os.utime(root, (0, 0), follow_symlinks=False)


def stage(args):
    _verify_digest(args.inrelease, args.inrelease_sha256, "InRelease")
    _verify_digest(args.release, args.release_sha256, "Release")
    _verify_digest(args.release_gpg, args.release_gpg_sha256, "Release.gpg")
    _verify_digest(args.packages_xz, args.packages_xz_sha256, "Packages")
    _verify_digest(args.packages_all_xz, args.packages_all_xz_sha256, "Packages-all")
    _verify_signature(
        args.launcher,
        args.inrelease,
        args.release,
        args.release_gpg,
        args.output,
        args.scratch,
    )

    verified = pathlib.Path(args.output) / "repository/verified-release"
    authenticated_release = verified.read_bytes()
    release = pathlib.Path(args.release).read_bytes()
    if authenticated_release != release:
        raise ValueError("authenticated InRelease does not match locked Release")
    package_bytes = pathlib.Path(args.packages_xz).read_bytes()
    _release_hash(authenticated_release, args.packages_path, len(package_bytes), args.packages_xz_sha256)
    packages_all_bytes = pathlib.Path(args.packages_all_xz).read_bytes()
    _release_hash(
        authenticated_release,
        args.packages_all_path,
        len(packages_all_bytes),
        args.packages_all_xz_sha256,
    )

    destination = pathlib.Path(args.output) / "repository"
    (destination / "dists/trixie/main/binary-amd64").mkdir(parents=True, exist_ok=True)
    _copy(args.inrelease, destination / "dists/trixie/InRelease")
    _copy(args.release, destination / "dists/trixie/Release")
    _copy(args.release_gpg, destination / "dists/trixie/Release.gpg")
    amd64_packages = destination / args.packages_path[:-3]
    all_packages = destination / args.packages_all_path[:-3]
    _decompress(args.packages_xz, amd64_packages)
    _decompress(args.packages_all_xz, all_packages)

    expected = {}
    filenames = set()
    local_names = set()
    for package in args.package_records:
        name, version, architecture, filename, digest, local_name = package.split("|", 5)
        key = (name, version, architecture)
        if key in expected:
            raise ValueError("duplicate locked package: %s" % "|".join(key))
        if filename in filenames:
            raise ValueError("package path collision: %s" % filename)
        if local_name in local_names:
            raise ValueError("duplicate local package name: %s" % local_name)
        _safe_package_path(filename)
        filenames.add(filename)
        local_names.add(local_name)
        expected[key] = (filename, digest, local_name)
    actual = {}
    for package_index in (amd64_packages, all_packages):
        with open(package_index, "rb") as source:
            for paragraph in _paragraphs(source.read()):
                key = (
                    paragraph.get("Package"),
                    paragraph.get("Version"),
                    paragraph.get("Architecture"),
                )
                if key in actual:
                    raise ValueError("duplicate package metadata: %s" % paragraph.get("Package"))
                if key in expected:
                    actual[key] = (paragraph.get("Filename"), paragraph.get("SHA256"))
    if actual.keys() != expected.keys():
        raise ValueError("locked packages do not match Packages metadata")
    for key in sorted(expected):
        if actual[key] != expected[key][:2]:
            raise ValueError("package metadata disagrees with lock: %s" % key[0])

    records_by_name = {value[2]: (key, value) for key, value in expected.items()}
    if set(records_by_name) != set(args.package_names):
        raise ValueError("package inputs do not match lock package names")
    for package, local_name in zip(args.packages, args.package_names):
        _, (remote_filename, digest, _) = records_by_name[local_name]
        _verify_digest(package, digest, "package %s" % local_name)
        relative = _safe_package_path(remote_filename)
        _copy(package, destination / relative)
    (destination / "dists/trixie/Release").chmod(0o644)
    verified.unlink()
    _set_deterministic_metadata(destination)


def main():
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
    parser.add_argument("--package", dest="package_records", action="append", default=[])
    parser.add_argument("--package-file", dest="packages", action="append", default=[])
    parser.add_argument("--package-name", dest="package_names", action="append", default=[])
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
