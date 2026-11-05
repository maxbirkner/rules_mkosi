# Compressed read-only release configuration fixture

This configuration tree builds a versioned release whose dm-verity root is a zstd-compressed erofs file system.
`Minimize=best` on the root and its verity partition places the file system and its hash tree at the start of fixed-size partitions, so the split artifacts end in zeros and the update payload is trimmed to them.
`ci/verify-release-reproducibility.sh` builds the image and its payload twice to check that `mkfs.erofs` and the payload are reproducible.
