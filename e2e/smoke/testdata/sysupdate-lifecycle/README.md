# A/B update lifecycle guest files

These rootfs payloads drive `sysupdate_lifecycle_test` and
`secure_boot_lifecycle_test` from inside the guest.
`rules-mkosi-ab-lifecycle` prints the serial markers that the host test
expects, trusts the test signer's certificate from the read-only virtio-9p
share `keyring`, and applies the next release with `systemd-sysupdate`, which
downloads it from the test's HTTP server (`http://10.0.2.100/after-<running
version>`) and verifies the signature of its `SHA256SUMS`. It then reboots.
It runs after `boot-complete.target` and `systemd-bless-boot.service`, so it can
check that a release was blessed. `rules-mkosi-ab-health.service` is installed
only in release 3; it always fails before `boot-complete.target`, which makes
systemd-boot fall back to release 2. `80-qemu-user.network` gives the guest a
static address on QEMU's user network. The preset enables both units and
`systemd-networkd`.

The driver also prints the `SecureBoot` and `SetupMode` EFI variables of each
boot. `secure_boot_lifecycle_test` boots the signed release 1 disk image,
updates to release 2 from a payload with a signed UKI, and expects the
firmware to refuse the unsigned UKI of release 3.
