"""Pinned Debian build-time userspace inputs."""

DEBIAN_TOOLS_DISTRIBUTION = "debian"
DEBIAN_TOOLS_RELEASE = "13"
DEBIAN_TOOLS_CODENAME = "trixie"
DEBIAN_TOOLS_ARCHITECTURE = "amd64"
DEBIAN_TOOLS_SNAPSHOT = "20250814T000000Z"
DEBIAN_TOOLS_SNAPSHOT_URL = "https://snapshot.debian.org/archive/debian/20250814T000000Z"
DEBIAN_TOOLS_LOCK_SHA256 = "8828eb8e8f4b207e8cd765ebabb1ebdf23ffd006893d5dbd7ddb65bd481c0077"
DEBIAN_TOOLS_ARCHIVE_SHA256 = "d9d4ebdb252324d84d2817397df31fd016fbb6020f4919e2effbf8f7958fd657"
DEBIAN_TOOLS_PYTHON_VERSION = "3.11.16"
DEBIAN_TOOLS_PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20260825/cpython-3.11.16%2B20260825-x86_64-unknown-linux-musl-lto%2Bstatic-full.tar.zst"
DEBIAN_TOOLS_PYTHON_SHA256 = "db37cb55adaf13d3eb78c56e76d2fcefaf7472945c8b52c17da60aede58d7529"

# The package lock is authoritative for package versions, URLs, hashes, and
# dependency edges.  These are the initial tracer-required command names.
DEBIAN_TOOLS_REQUIRED_COMPONENTS = [
    "apt-get",
    "dpkg",
    "systemd-repart",
    "mkfs.ext4",
    "mkfs.fat",
    "mkfs.btrfs",
    "sfdisk",
    "parted",
    "grub-install",
    "bootctl",
    "objcopy",
]

DEBIAN_TOOLS_COMPONENT_MANIFEST = "@rules_mkosi//mkosi/debian:components.txt"
