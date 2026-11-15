# arm64 release configuration fixture

A bootable arm64 release image with an unsigned UKI, an erofs root protected by dm-verity, and an empty second A/B slot, from the built-in arm64 Debian snapshot.
Tests of arm64 boot artifacts, such as device trees, extend this fixture rather than declaring their own.
