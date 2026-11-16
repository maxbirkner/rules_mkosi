"""Pinned Debian build-time userspace inputs."""

DEBIAN_TOOLS_DISTRIBUTION = "debian"
DEBIAN_TOOLS_RELEASE = "13"
DEBIAN_TOOLS_CODENAME = "trixie"
DEBIAN_TOOLS_ARCHITECTURE = "amd64"
DEBIAN_TOOLS_SNAPSHOT = "20260912T080811Z"
DEBIAN_TOOLS_SNAPSHOT_URL = "https://snapshot.debian.org/archive/debian/20260912T080811Z"
DEBIAN_TOOLS_LOCK_SHA256 = "79dc5b18fcefba9a66a7fb58b89bd5fe8abce8356f42800ed355db9e2f66f2dd"

# The built-in arm64 lock resolves the same package set for arm64 at the same snapshot. It provides
# @mkosi_debian_snapshot_arm64.
DEBIAN_TOOLS_ARM64_LOCK_SHA256 = "b61aa0d003f1b059faf6836df489f51020521848c9711e1423aa4fa5973f30c1"
DEBIAN_TOOLS_ARCHIVE_SHA256 = "e062f768d137cb0bb2beacf4266c382ce8334aa9a28a7f537d0583f7ffbd9258"
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
    "cpp",
    "dtc",
    "fdtoverlay",
]

DEBIAN_TOOLS_COMPONENT_MANIFEST = "@rules_mkosi//mkosi/debian:components.txt"
