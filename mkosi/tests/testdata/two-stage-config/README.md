# Two-stage finalize configuration fixture

This configuration tree finalizes the [`two-stage-base-config`](../two-stage-base-config) base for one image version.
It installs no packages and adds only the version-dependent settings: the boot loader, the UKI, and the kernel command line, with mkosi's default ESP and root partitions.
It has no dm-verity slots so that the reproducibility manifest can project it; the end-to-end A/B fixtures finalize a dm-verity base.
