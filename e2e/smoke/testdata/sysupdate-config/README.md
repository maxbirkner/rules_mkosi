# A/B release configuration fixture

This configuration tree finalizes the
[`sysupdate-base-config`](../sysupdate-base-config) base into a versioned
immutable release with one populated slot and one inactive `_empty` slot,
following the systemd-sysupdate partition conventions. It installs no
packages. The image id and version are supplied by
`mkosi_image(image_id, image_version)`, or by `image_version_file` for
release 2, and appear in the partition labels
through repart's `%M` and `%A` specifiers. `UnifiedKernelImageFormat=%i_%v`
names the UKI as the transfer definitions expect.

`Seed=` and `SourceDateEpoch=` must match the base. The kernel command
line keeps `/var` volatile because the root is read-only and the fixture does
not create a `var` partition.
