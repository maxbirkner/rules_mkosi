# arm64 release configuration fixture

A bootable arm64 release image with an unsigned UKI, an erofs root protected by dm-verity, and an empty second A/B slot, from the built-in arm64 Debian snapshot.
Tests of arm64 boot artifacts, such as device trees, extend this fixture rather than declaring their own.

The UKI carries three device trees as `.dtbauto` sections: `rules-mkosi-test-board.dtb` from the image's `devicetrees` label, and the two small Arm Corstone-1000 device trees that `Devicetrees=` selects from Debian's arm64 kernel package below `/usr/lib/linux-image-<kver>/arm/`.
systemd-stub installs a `.dtbauto` section only on hardware with a matching compatible string, so they do not affect boots on other machines such as QEMU's `virt`.
A single device tree would become a `.dtb` section, which systemd-stub installs on every machine.
