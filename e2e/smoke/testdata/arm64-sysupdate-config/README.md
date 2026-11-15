# arm64 A/B release configuration fixture

The arm64 counterpart of [`sysupdate-config`](../sysupdate-config): it finalizes the [`arm64-sysupdate-base-config`](../arm64-sysupdate-base-config) base into a versioned immutable release with one populated slot and one inactive `_empty` slot.
Its partitions have the `root-arm64` and `root-arm64-verity` types and the sizes of the [release example](../../example/mkosi.repart); the ESP is 512 MiB because the UEFI firmware does not mount a FAT32 file system with fewer than 65525 clusters.
The serial console is `ttyAMA0`, the PL011 port of QEMU's `virt` machine.
