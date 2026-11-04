"""Pinned Debian build-time userspace inputs."""

DEBIAN_TOOLS_DISTRIBUTION = "debian"
DEBIAN_TOOLS_RELEASE = "13"
DEBIAN_TOOLS_CODENAME = "trixie"
DEBIAN_TOOLS_ARCHITECTURE = "amd64"
DEBIAN_TOOLS_SNAPSHOT = "20260912T080811Z"
DEBIAN_TOOLS_SNAPSHOT_URL = "https://snapshot.debian.org/archive/debian/20260912T080811Z"
DEBIAN_TOOLS_LOCK_SHA256 = "38c9e6d7e3585c0b6ce5ccd71b03eababc0d6e2a0f0ffce77d1e6843e11fb4d8"
DEBIAN_TOOLS_ARCHIVE_SHA256 = "95049fee1d6eda13d3390aec5c473ab73e96dc7fe3b644ee58d941ecce2404e3"
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
