# arm64 release configuration fixture

A bootable arm64 release image with an unsigned UKI, an erofs root protected by dm-verity, and an empty second A/B slot, from the built-in arm64 Debian snapshot.
Tests of arm64 boot artifacts, such as device trees, extend this fixture rather than declaring their own.

`Devicetrees=` selects the two small Arm Corstone-1000 device trees that Debian's arm64 kernel package ships below `/usr/lib/linux-image-<kver>/arm/`.
Two matches become `.dtbauto` sections, which systemd-stub installs only on hardware with a matching compatible string, so they do not affect boots on other machines such as QEMU's `virt`.
A single match would become a `.dtb` section, which systemd-stub installs on every machine.
