# arm64 release configuration fixture

A bootable arm64 release image with an unsigned UKI, an erofs root protected by dm-verity, and an empty second A/B slot, from the built-in arm64 Debian snapshot.
Tests of arm64 boot artifacts, such as device trees, extend this fixture rather than declaring their own.

The UKI carries three device trees as `.dtbauto` sections: `virt_dtb` from the image's `devicetrees`, and the two small Arm Corstone-1000 device trees that `Devicetrees=` selects from Debian's arm64 kernel package below `/usr/lib/linux-image-<kver>/arm/`.
`virt_dtb` is the device tree of QEMU's `virt` machine without ACPI, to which the `devicetree` rule applies the overlay `uki-devicetree.dtso`: it sets the model `rules-mkosi UKI device tree` and adds the compatible string `rules-mkosi,uki-devicetree`.
systemd-stub installs a `.dtbauto` section only if its first compatible string equals that of the device tree that the firmware passes:

- `uki_release_boot_test` boots `virt` with ACPI, where the firmware passes no device tree, so none is installed and Linux uses ACPI.
- `uki_release_devicetree_boot_test` boots `virt,acpi=off`, where the firmware passes QEMU's device tree, compatible with `linux,dummy-virt`, so systemd-stub installs `virt_dtb`.
  The test checks that Linux prints `Machine model: rules-mkosi UKI device tree`, and that `/sys/firmware/devicetree/base/compatible` lists `rules-mkosi,uki-devicetree`.

A single device tree would become a `.dtb` section, which systemd-stub installs on every machine.
