"""Passes the built-in Debian tools provenance to Python tests, so they need no copies of its values."""

load(
    "//mkosi/debian:provenance.bzl",
    "DEBIAN_TOOLS_ARCHIVE_SHA256",
    "DEBIAN_TOOLS_LOCK_SHA256",
    "DEBIAN_TOOLS_SNAPSHOT",
    "DEBIAN_TOOLS_SNAPSHOT_URL",
)

# The debian_snapshot record that the build metadata of a release image built with the built-in tools contains.
_DEBIAN_SNAPSHOT_METADATA = {
    "architecture": "amd64",
    "codename": "trixie",
    "components": ["main"],
    "format_version": "debian-snapshot-v1",
    "lock_sha256": DEBIAN_TOOLS_LOCK_SHA256,
    "snapshot": DEBIAN_TOOLS_SNAPSHOT,
    "snapshot_url": DEBIAN_TOOLS_SNAPSHOT_URL,
}

DEBIAN_TOOLS_PROVENANCE_ENV = {
    "DEBIAN_TOOLS_ARCHIVE_SHA256": DEBIAN_TOOLS_ARCHIVE_SHA256,
    "DEBIAN_TOOLS_LOCK_SHA256": DEBIAN_TOOLS_LOCK_SHA256,
    "DEBIAN_TOOLS_SNAPSHOT": DEBIAN_TOOLS_SNAPSHOT,
    "DEBIAN_TOOLS_SNAPSHOT_METADATA": json.encode(_DEBIAN_SNAPSHOT_METADATA),
    "DEBIAN_TOOLS_SNAPSHOT_URL": DEBIAN_TOOLS_SNAPSHOT_URL,
}
