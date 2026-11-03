# A/B release configuration fixture

This configuration tree finalizes the [`sysupdate-base-config`](../sysupdate-base-config) base into a versioned immutable release with one populated slot and one inactive `_empty` slot.
It installs no packages.
`mkosi_image` supplies the image id and version (through `image_version_file` for release 2), which appear in the partition labels through repart's `%M` and `%A` and in the UKI name through `UnifiedKernelImageFormat=%i_%v`.

`Seed=` and `SourceDateEpoch=` match the base.
The kernel command line keeps `/var` volatile because the root is read-only and the fixture has no `var` partition.
