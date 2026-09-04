# systemd-sysupdate A/B bundles

`sysupdate_ab` projects two immutable `mkosi_image` releases into a typed,
UEFI-only update contract. Each slot contains a root filesystem, matching
dm-verity hash tree, externally signed UKI, and explicit version. Consumers
select these files through `SysupdateAbInfo`; filenames are not an API.

The normalized layout uses the Discoverable Partitions Specification
`root-x86-64` and `root-x86-64-verity` type GUIDs. It rejects unequal slot
sizes, overlaps, non-MiB-aligned ranges, duplicate versions, unsigned UKIs,
and BIOS images. The JSON projection records SHA-256 and size for every
transfer artifact.

The generated `*.transfer` files target two partition instances and the
Boot Loader Specification Type #2 UKIs in `$BOOT/EFI/Linux`. New UKIs use
systemd-boot's `name_@v+@l-@d.efi` boot-counting convention. Three attempts
are configured by default; `systemd-bless-boot.service` commits a successful
boot. If all attempts fail, systemd-boot falls back to the older entry.

## Firmware and signing policy

A shared ESP is used because systemd-boot and Type #2 UKIs are UEFI
interfaces. XBOOTLDR is not emitted by this first contract. BIOS/SeaBIOS is
rejected during Bazel analysis rather than silently producing an update that
cannot participate in boot assessment.

The rule accepts only `SecureBootSignedUkiInfo`, the output of the offline
signing import boundary. It never accepts or exposes a private key.

## Execution boundary

The bundle is offline and cache-safe: all payloads are declared Bazel inputs
and its projection performs no network access. The guest image must install
Debian's snapshot-pinned `systemd-container` package, which provides the
declared `SysupdateAbInfo.sysupdate_binary` path
(`/usr/lib/systemd/systemd-sysupdate`). Applying a bundle requires a writable
disk containing the declared preallocated slots.
