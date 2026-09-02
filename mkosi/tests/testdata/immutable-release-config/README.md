# Immutable release configuration fixture

This complete configuration tree exercises unsigned UKI and hash-only dm-verity
in the cache-safe offline release mode.
Package-manager cache and log trees are removed because their transient state
is not part of the release artifact.
