# Two-stage finalize configuration fixture

This configuration tree finalizes the
[`two-stage-base-config`](../two-stage-base-config) base for one image
version. It installs no packages; it only adds the version-dependent settings:
the A/B partition layout labelled through repart's `%M` and `%A` specifiers,
the boot loader, the UKI, and the kernel command line. `mkosi_image(base = ...)`
supplies the base root as `BaseTrees=` and its default initrd as `Initrds=`.
