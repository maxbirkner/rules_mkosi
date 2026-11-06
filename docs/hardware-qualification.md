# Physical hardware qualification

CI boots every change in QEMU; physical qualification adds evidence that the images of one rules_mkosi release boot, update, and enforce their security tier on real x86-64 machines.
A release claims a hardware class only through a [sign-off record](#release-sign-off) with attached, passing results for that exact release.
No release claims any class yet.

A claim covers the tested machine models and firmware versions of a class; other models of the class are expected, not promised, to work.
This process does not cover purchasing hardware, a remote lab, or power interruption during updates.

## Firmware tiers

| Tier | Boot chain | Integrity | Qualified on hardware with |
| --- | --- | --- | --- |
| `uefi` | UEFI firmware, systemd-boot, UKI | dm-verity root, A/B updates with boot counting, optional [Secure Boot](secure-boot.md) | `uefi-*` classes |
| `bios` | BIOS or UEFI CSM, GRUB i386-pc ([legacy BIOS](../README.md#legacy-bios)) | None: no UKI, dm-verity, Secure Boot, or A/B updates | `bios-*` classes |

## Hardware classes

Generations are approximate and only guide the choice of a representative machine.

| Class | Representative machine | Generation | Boot disk | Network | Console | Secure Boot states | TPM2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `uefi-modern-desktop` | Desktop, small form factor, or mini PC with a plug-in GPU or NIC | 2019 or newer | NVMe | Wired | Graphical | `disabled`, `setup-mode`, `custom-keys` | Present |
| `uefi-mobile-apu` | Laptop or handheld with an AMD APU or Intel mobile SoC, such as a handheld AMD APU device with NVMe, Wi-Fi and fTPM in UEFI setup mode | 2020 or newer | NVMe | Wi-Fi with firmware | Graphical (internal display) | `disabled`, `setup-mode` | Present |
| `uefi-embedded-headless` | Fanless industrial box without display | 2016 or newer | eMMC or SATA | Wired, several ports | Serial | `setup-mode`, `custom-keys` | Any |
| `uefi-older-generation` | Office desktop of an early UEFI generation | 2012 to 2018 | SATA | Wired | Graphical | `disabled`, `microsoft-factory-keys` | Absent or TPM 1.2 |
| `uefi-removable-usb` | Any UEFI machine starting from the removable-media path | Any | USB | Wired | Graphical | `disabled` | Any |
| `bios-legacy-only` | Desktop without UEFI | 2006 to 2012 | SATA | Wired | Graphical (VGA text), serial if present | `not-applicable` | Absent |
| `bios-csm` | UEFI machine booting through its Compatibility Support Module | 2012 to 2020 | SATA | Wired | Graphical | `not-applicable` | Any |

A class is qualified when, for each of its Secure Boot states, at least one result record passes every [required check](#checks).
One result record covers one machine in one firmware configuration, so each Secure Boot state needs its own run.

### Secure Boot states

| State | Firmware before the first boot | Image | Expected result |
| --- | --- | --- | --- |
| `disabled` | Secure Boot off | Unsigned UEFI release image | Boots; `bootctl status` reports Secure Boot disabled. |
| `setup-mode` | Secure Boot on, no PK enrolled | [`secure_boot_signed_image`](secure-boot.md#signed-disk-images-and-key-auto-enrollment) with `auto_enroll_keys` and `secure_boot_enroll = "force"` | systemd-boot enrolls the keys and resets; then Secure Boot is enforced. |
| `custom-keys` | Qualification PK, KEK, and db already enrolled | `secure_boot_signed_image` without `auto_enroll_keys` | Signed binaries boot; an unsigned UKI is refused. |
| `microsoft-factory-keys` | Vendor default keys | `secure_boot_signed_image` without `auto_enroll_keys` | The firmware refuses the custom-signed systemd-boot, which proves enforcement and the need for enrollment. |
| `not-applicable` | BIOS or CSM boot, Secure Boot off | BIOS release image | Secure Boot does not apply. |

Record in `db_includes_microsoft_uefi_ca` whether db holds the Microsoft UEFI CA certificates; `uefi-modern-desktop` needs them for the option ROM of its plug-in card.

## Checks

Required checks follow from the tier and the dimensions of a class.
Run the on-device commands as root on the booted image and attach their output.
A `microsoft-factory-keys` run requires only `artifact-digest`, `identity`, and `secure-boot-enforcement`, because nothing else boots; take its identity from the firmware setup screen or from a `disabled` run with the same firmware version.

| Check | Required when | Passes when |
| --- | --- | --- |
| `artifact-digest` | Always | `sha256sum` of the written file and of the device read back to the file's size match `written_sha256`. |
| `identity` | Always | `/sys/class/dmi/id/` and `/proc/cpuinfo` values are recorded in `machine`. |
| `firmware-boot` | Always | The firmware starts the boot loader from the boot disk without a manually created boot entry. |
| `boot-chain` | Always | `uefi`: `bootctl status` reports systemd-boot and the UKI's systemd-stub. `bios`: `/sys/firmware/efi` is absent and the console shows GRUB. |
| `boot-to-userspace` | Always | `systemctl is-system-running --wait` prints `running`. |
| `storage` | Always | `lsblk -d -o NAME,TRAN,MODEL` shows the class's transport for the boot disk, and `journalctl -k -p err` has no storage errors. |
| `reboot-poweroff` | Always | `systemctl reboot` and `systemctl poweroff` complete within two minutes each. |
| `tpm2` | Always | `systemd-creds has-tpm2` matches `machine.tpm2`, and boot does not depend on the TPM. |
| `verity-root` | `uefi` | `findmnt -no SOURCE,OPTIONS /` shows a read-only `/dev/mapper/` device, and `/proc/cmdline` contains `roothash=`. |
| `ab-update` | `uefi` | Release N+1 installs with `systemd-sysupdate` and is blessed, and release N+2, whose health check fails, rolls back, as in [boot assessment](sysupdate-ab.md#boot-assessment-and-rollback). |
| `network-wired` | Wired network | The interface is `routable` in `networkctl status`; for `uefi`, the `ab-update` releases download [over HTTP](sysupdate-ab.md#updates-over-http) through it. |
| `network-wifi` | Wi-Fi | `journalctl -k` shows the firmware loaded without errors, and the interface is `routable` on a test access point. |
| `console-serial` | Serial console | The serial capture shows boot loader, kernel, and login prompt. |
| `console-graphical` | Graphical console | The display shows the boot menu, kernel output, and login prompt; attach a photo or recording. |
| `secure-boot-state` | `uefi` | `bootctl status` reports the state that the run expects. |
| `secure-boot-enrollment` | `setup-mode` | The console shows `Custom Secure Boot keys successfully enrolled`, and the next boot reports Secure Boot `enabled (user)`. |
| `secure-boot-enforcement` | `setup-mode`, `custom-keys`, `microsoft-factory-keys` | The firmware refuses an unsigned or untrusted binary with `Access denied`, as in [refused releases](secure-boot.md#releases-that-the-firmware-refuses). |
| `option-rom` | `custom-keys` or `setup-mode` with a plug-in GPU or NIC | Display and network of the plug-in card work with Secure Boot enforced. |

## Automated VM gates

Physical qualification starts only from a commit on `main` whose `CI conclusion` passed, which runs these gates on every change.
VM gates do not replace physical gates, and physical gates do not replace VM gates.

| Gate | Targets | Proves |
| --- | --- | --- |
| UEFI firmware | `//mkosi/tests:qemu_ovmf_smoke_test`, also with `--config=kvm_unavailable` | OVMF starts, with KVM and with the TCG fallback. |
| UEFI boot | `e2e/smoke` `//:uefi_boot_test` | A tracer image boots under OVMF and powers off cleanly. |
| BIOS boot | `//mkosi/tests:bios_boot_test`, `e2e/smoke` `//:bios_boot_test` | A release image boots GRUB i386-pc under SeaBIOS with KVM. |
| UKI and dm-verity | `e2e/smoke` `//:release_demo_verity_boot_test`, `//:release_demo_verity_corruption_boot_test` | The verity root mounts, and a corrupted root is rejected. |
| A/B updates | `e2e/smoke` `//:sysupdate_lifecycle_test` | A signed HTTP update is blessed, and a failing release rolls back. |
| Secure Boot | `e2e/smoke` `//:secure_boot_lifecycle_test` | Keys enroll from Setup Mode, signed updates boot, and an unsigned UKI is refused. |
| Reproducibility | `ci/verify-release-reproducibility.sh`, `e2e/smoke` `//:release_demo_reproducibility_test` | Release images rebuild to identical manifests. |

Only physical gates cover vendor firmware (boot entries, removable-media fallback, key enrollment, option ROMs), storage controllers and their initrd drivers, Wi-Fi firmware, displays, real TPMs, and power cycling.

## Provisioning

1. Create a Bazel module for the qualification images that pins rules_mkosi to the candidate commit with `git_override(commit = ...)`, or to a published release with `bazel_dep`, whose registry entry pins the archive's integrity.
2. Build release-mode images (`mode = "release"`) from a [locked snapshot](../README.md#debian-snapshots) whose specification adds the firmware, microcode, and Wi-Fi packages of the classes from `non-free-firmware`.
   Install and enable `systemd-networkd` with DHCP, and add `console=tty0 console=ttyS0,115200n8` to `KernelCommandLine=`.
   - `uefi`: a versioned image with `unified_kernel_image = "unsigned"`, `verity = "hash"`, and the [A/B layout](sysupdate-ab.md#partition-layout), and payloads for releases N+1 and N+2 as in [`e2e/smoke`](../e2e/smoke/BUILD.bazel), where N+2 fails its health check.
   - `bios`: an image with `firmware = "bios"`.
3. Build an [`mkosi_reproducibility_manifest`](../README.md#public-api) of each image and record the SHA-256 of the manifest and its `raw_image.canonical_sha256`.
4. For Secure Boot states, sign the UKIs and systemd-boot [offline](secure-boot.md) with a qualification key set whose PK private key you keep, and record the SHA-256 of the signed binaries, the `.auth` files, and the record of `secure_boot_signed_image`.
   Never enroll the keys of `secure_boot_ephemeral_test_fixture` on hardware: its PK private key is discarded, so the keys could never be rotated.
5. Sign the update payloads [offline](sysupdate-ab.md#signing-sha256sums-offline) with a qualification OpenPGP key, ship its certificate in the images, publish the payloads on a LAN web server, and record the SHA-256 of each `SHA256SUMS`.
6. Reset the firmware to its defaults, record its version and every changed setting, and set the Secure Boot state of the run.
7. Check the image with `sha256sum`, write it with `dd if=<image> of=/dev/<disk> bs=4M conv=fsync`, and read the device back to the image's size to check the digest again.
8. Boot, capture the serial console or record the display, run the [checks](#checks), and save their output to `logs/`.

## Evidence

Each run produces one directory with a result record `result.json` and a `logs/` directory.
The record follows [`hardware-qualification-result.schema.json`](hardware-qualification-result.schema.json) and binds the run to immutable digests: the rules_mkosi commit and archive, the reproducibility manifest, the written image, signed binaries, and update payloads.
Every passed or failed check references at least one log by path and SHA-256.
Remove serial numbers, MAC addresses, and network credentials from logs before hashing them.

`outcome` is `passed` only if every required check passed.
It is `invalid` when a failure is attributed to `procedure` or to a defective unit (`hardware` with category `hardware-fault`); repeat such a run.

```json
{
  "format_version": "rules-mkosi-hardware-qualification-result-v1",
  "class": "uefi-mobile-apu",
  "subject": {
    "rules_mkosi": {
      "commit": "0123456789abcdef0123456789abcdef01234567"
    },
    "image": {
      "reproducibility_manifest_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
      "canonical_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
      "written_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
      "signed_image_record_sha256": "4444444444444444444444444444444444444444444444444444444444444444"
    },
    "update_payloads": [
      {
        "version": "2",
        "sha256sums_sha256": "5555555555555555555555555555555555555555555555555555555555555555",
        "expected": "blessed"
      }
    ]
  },
  "machine": {
    "dmi": {
      "sys_vendor": "Example Vendor",
      "product_name": "Example Handheld",
      "bios_vendor": "Example Firmware",
      "bios_version": "1.2.3",
      "bios_date": "01/02/2026"
    },
    "cpu": "Example AMD APU",
    "boot_disk": {
      "transport": "nvme",
      "model": "Example NVMe 512GB"
    },
    "network": [
      {
        "kind": "wifi",
        "driver": "mt7921e",
        "firmware": ["mediatek/WIFI_RAM_CODE_MT7961_1.bin"]
      }
    ],
    "consoles": ["graphical"],
    "tpm2": "firmware"
  },
  "firmware": {
    "tier": "uefi",
    "boot_mode": "uefi",
    "secure_boot": "setup-mode",
    "db_includes_microsoft_uefi_ca": true,
    "settings": ["Reset to defaults", "Secure Boot keys cleared"]
  },
  "operator": "qualifier@example.com",
  "started_at": "2026-11-06T09:00:00Z",
  "finished_at": "2026-11-06T10:30:00Z",
  "checks": [
    {
      "id": "secure-boot-enrollment",
      "status": "failed",
      "logs": [
        {
          "path": "logs/display-first-boot.mp4",
          "sha256": "6666666666666666666666666666666666666666666666666666666666666666"
        }
      ],
      "failure": {
        "category": "secure-boot",
        "attribution": "firmware",
        "summary": "The firmware leaves Setup Mode only after a second reset."
      }
    }
  ],
  "outcome": "failed"
}
```

### Failure taxonomy

Every failed check names one category and one attribution.

| Category | Examples |
| --- | --- |
| `provisioning` | Digest mismatch, incomplete write, wrong artifact. |
| `firmware-boot` | No boot entry, removable-media path ignored, CSM cannot boot the disk. |
| `secure-boot` | Enrollment refused, signed binary refused, unsigned binary started, option ROM blocked. |
| `boot-loader` | systemd-boot or GRUB fails, wrong entry, boot counting ignored. |
| `kernel-initrd` | Panic, missing storage or display driver, root device not found. |
| `root-integrity` | dm-verity rejects an unmodified image, or a modified root is accepted. |
| `storage` | Controller or I/O errors, slot write failure. |
| `network` | No link or address, missing Wi-Fi firmware, association failure. |
| `console` | No serial or display output. |
| `update-rollback` | Update not installed or not blessed, no rollback. |
| `tpm` | Reported TPM differs from the machine, or boot depends on it. |
| `power-state` | Reboot or power-off hangs. |
| `hardware-fault` | Defective unit, not reproducible on a second unit. |

| Attribution | Consequence |
| --- | --- |
| `rules-mkosi` | Open an issue; the class cannot be claimed until a release fixes it. |
| `image-configuration` | Fix the qualification image, such as a missing firmware package, and rerun. |
| `firmware` | Document the vendor behavior and its workaround; the class is claimed only if a run with the workaround passes. |
| `hardware` | Rerun on another unit. |
| `procedure` | Rerun following this document. |

A `secure-boot` or `root-integrity` failure in which untrusted code or content runs blocks the release regardless of attribution.

## Release sign-off

A release sign-off record follows [`hardware-qualification-signoff.schema.json`](hardware-qualification-signoff.schema.json).
It names the tag, its commit, and the archive's SHA-256, links the CI run of that commit, and lists every class as `qualified`, `failed`, or `not-tested`.
A `qualified` class references the passing result records of all its Secure Boot states by asset name and SHA-256, and each of them names the tag's commit.
Results of an earlier release do not carry over.

1. Qualify the commit that the [release](../.bcr/README.md#releasing) will tag, before tagging it.
2. After the release workflow, attach the sign-off record and an archive of the evidence directories to the GitHub release:

   ```console
   gh release upload v1.2.3 hardware-qualification.json hardware-qualification-evidence.tar.gz
   ```

3. Add a "Hardware qualification" section to the release notes with `gh release edit v1.2.3 --notes-file <notes>`, listing only the `qualified` classes with their tested models and firmware versions.

A release without the sign-off asset claims no hardware class, and a class without a referenced, attached, passing result is not claimed.
