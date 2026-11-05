# Immutable release configuration fixture

This complete configuration tree exercises unsigned UKI and hash-only dm-verity
through the public release mode.
Package-manager cache and log trees are removed because their transient state
is not part of the release artifact.

`mkosi_config_tree` adds `../shared-tree` to both `mkosi.extra/` and
`mkosi.initrd.conf/mkosi.extra/`. Its executable systemd generator prints a
serial marker when the default initrd starts, and the root keeps it executable.
