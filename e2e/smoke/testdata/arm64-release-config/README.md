# arm64 release configuration fixture

An arm64 release image with an unsigned UKI and a dm-verity protected root, from the built-in arm64 Debian snapshot.
On Linux x86-64 it is cross-built.
Its `Devicetrees=` selects two device trees of Debian's arm64 kernel package, which become `.dtbauto` sections of the UKI together with the device tree of the image's `devicetrees` label.
