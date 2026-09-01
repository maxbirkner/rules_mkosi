"""Pinned Debian build-time userspace inputs."""

DEBIAN_TOOLS_DISTRIBUTION = "debian"
DEBIAN_TOOLS_RELEASE = "13"
DEBIAN_TOOLS_CODENAME = "trixie"
DEBIAN_TOOLS_ARCHITECTURE = "amd64"
DEBIAN_TOOLS_SNAPSHOT = "20250814T000000Z"
DEBIAN_TOOLS_SNAPSHOT_URL = "https://snapshot.debian.org/archive/debian/20250814T000000Z"
DEBIAN_TOOLS_LOCK_SHA256 = "02828b2d265fc6ff59e6a41bd05168247bc6a575461eaca239df1ec9552839d8"
DEBIAN_TOOLS_ARCHIVE_SHA256 = "522f1ad5d2494f767092c1fe8051f0e0b053f9c6fafb97b7041bc28a652e359c"
DEBIAN_TOOLS_PYTHON_VERSION = "3.14.7"
DEBIAN_TOOLS_PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20260825/cpython-3.14.7%2B20260825-x86_64-unknown-linux-musl-lto%2Bstatic-full.tar.zst"
DEBIAN_TOOLS_PYTHON_SHA256 = "1709517f7f9a642ecbec562c3612989a7b1b6b5638db61803f993185d4ae2df7"

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
