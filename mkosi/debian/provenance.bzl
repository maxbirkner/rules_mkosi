"""Pinned Debian build-time userspace inputs."""

DEBIAN_TOOLS_DISTRIBUTION = "debian"
DEBIAN_TOOLS_RELEASE = "13"
DEBIAN_TOOLS_CODENAME = "trixie"
DEBIAN_TOOLS_ARCHITECTURE = "amd64"
DEBIAN_TOOLS_SNAPSHOT = "20260912T080811Z"
DEBIAN_TOOLS_SNAPSHOT_URL = "https://snapshot.debian.org/archive/debian/20260912T080811Z"
DEBIAN_TOOLS_LOCK_SHA256 = "c2528f32656b458f02861fdb957737b40ed4b3efec57a8bd9a781063866d7b53"
DEBIAN_TOOLS_ARCHIVE_SHA256 = "f6566f5ee51f5d86a1332814631ebc935aa716600d7787138f161fb902a651c2"
DEBIAN_TOOLS_PYTHON_VERSION = "3.14.10"
DEBIAN_TOOLS_PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.14.10%2B20261026-x86_64-unknown-linux-musl-lto%2Bstatic-full.tar.zst"
DEBIAN_TOOLS_PYTHON_SHA256 = "58733bc01987f9a5b6e7436f71dc338b1d9e47ec4713e7a123050f42d9160cac"

# The package lock is authoritative for package versions, URLs, hashes, and
# dependency edges.  These are the initial tracer-required command names.
DEBIAN_TOOLS_REQUIRED_COMPONENTS = [
    "apt-get",
    "dpkg",
    "systemd-repart",
    "mkfs.ext4",
    "mkfs.fat",
    "mkfs.btrfs",
    "mkfs.erofs",
    "sfdisk",
    "parted",
    "grub-install",
    "grub-bios-modules",
    "bootctl",
    "objcopy",
    "openssl",
    "systemd-sbsign",
]

DEBIAN_TOOLS_COMPONENT_MANIFEST = "@rules_mkosi//mkosi/debian:components.txt"
