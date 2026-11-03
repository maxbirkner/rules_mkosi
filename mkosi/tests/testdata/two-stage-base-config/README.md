# Two-stage base configuration fixture

This configuration tree is the version-independent part of a two-stage
release: `mkosi_base` installs its packages from the built-in Debian snapshot
and archives the root together with mkosi's default initrd. It deliberately
contains no partition, boot loader, UKI, or kernel command line settings;
those belong to the finalize configuration in
[`two-stage-config`](../two-stage-config).
