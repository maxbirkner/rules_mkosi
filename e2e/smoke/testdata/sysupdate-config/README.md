# A/B release configuration fixture

This configuration tree finalizes the [`sysupdate-base-config`](../sysupdate-base-config) base into a versioned immutable release with one populated slot and one inactive `_empty` slot.
It installs no packages.
`mkosi_image` supplies the image id and version (through `image_version_file` for release 2), which appear in the partition labels through repart's `%M` and `%A` and in the UKI name through `UnifiedKernelImageFormat=%i_%v`.

The partitions are those of the [release example](../../example/mkosi.repart), which `//:sysupdate_config_tree` adds as `mkosi.repart`.
The populated root is a zstd-compressed erofs file system, and `Minimize=best` on it and its verity partition keeps the update payload at the compressed size while both slots stay 512 MiB.
`Seed=` and `SourceDateEpoch=` match the base.
The kernel command line keeps `/var` volatile because the root is read-only and the fixture has no `var` partition.
