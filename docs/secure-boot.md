# Secure Boot and offline signing

rules_mkosi never handles a production signing key.
`mkosi_image(unified_kernel_image = "unsigned")` builds a deterministic, cacheable unsigned UKI; a signer outside Bazel signs it, and Bazel verifies the result.
The same flow signs any other PE/COFF binary on a release image's ESP, such as systemd-boot.

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "secure_boot_import_response", "secure_boot_signing_request")

secure_boot_signing_request(
    name = "os_signing_request",
    image = ":os",                 # Release image with unified_kernel_image = "unsigned".
    certificate = "db.crt",        # The signer's public certificate (one PEM or DER X.509 object).
)

secure_boot_import_response(
    name = "os_signed_uki",
    request = ":os_signing_request",
    signed_binary = "signed/os.efi",  # Returned by the external signer.
)

# systemd-boot; EFI/BOOT/BOOTX64.EFI is the same binary.
secure_boot_signing_request(
    name = "systemd_boot_signing_request",
    image = ":os",
    certificate = "db.crt",
    esp_path = "EFI/systemd/systemd-bootx64.efi",
)

secure_boot_import_response(
    name = "systemd_boot_signed",
    request = ":systemd_boot_signing_request",
    signed_binary = "signed/systemd-bootx64.efi",
)
```

1. `secure_boot_signing_request` outputs the unsigned binary, the normalized certificate, and a JSON request (`mkosi-secure-boot-signing-request-v3`).
   The request binds the binary's digest, its `esp_path` (empty for the UKI), the `authenticode-sha256` algorithm, and the certificate fingerprint; `context` is `uefi-secure-boot-uki` or `uefi-secure-boot-esp-file`.
   With `esp_path`, the binary is read from the image's ESP.
   It returns `SecureBootSigningRequestInfo`.
2. The external signer validates the request, Authenticode-signs exactly that binary, and returns the signed PE file.
3. `secure_boot_import_response` accepts the signed binary only if it carries exactly one RSA/SHA-256 Authenticode signature by the expected certificate and removing that signature (with the PE checksum and certificate-table fields it changes) yields exactly the requested binary.
   It returns `SecureBootSignedBinaryInfo` with `signed_binary`, `esp_path`, the signer `certificate`, and verification metadata.

Pass a signed UKI as `sysupdate_payload(signed_uki = ...)` to ship it in an [A/B update](sysupdate-ab.md#update-payloads).

## Signed disk images and key auto-enrollment

`secure_boot_signed_image` turns an unsigned UEFI release image into the disk image that you write to a device once.
Its ESP holds the signed boot binaries and, optionally, the keys that systemd-boot enrolls on first boot.

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "secure_boot_signed_image")

secure_boot_signed_image(
    name = "os_installer",
    image = ":os",
    signed_binaries = [":os_signed_uki", ":systemd_boot_signed"],
    auto_enroll_keys = ["keys/PK.auth", "keys/KEK.auth", "keys/db.auth"],  # Optionally keys/dbx.auth.
    secure_boot_enroll = "force",
)
```

- Every ESP file with the bytes of a request's unsigned binary is replaced by its signed binary, so one signed systemd-boot replaces both `EFI/systemd/systemd-bootx64.efi` and `EFI/BOOT/BOOTX64.EFI`, and the signed UKI replaces the UKI under its boot-counted name.
  The build fails if a signed binary has no unsigned copy on the ESP, or if any other unsigned PE/COFF binary stays on the ESP, because the firmware would refuse to load it.
- `auto_enroll_keys` are public, pre-signed UEFI authenticated variables (`.auth` files) that you create outside Bazel with the PK and KEK private keys, for example with `sbvarsign` or `bootctl install --secure-boot-auto-enroll=yes`.
  They are copied to `/loader/keys/auto/`, and `loader.conf` gets `secure-boot-enroll` set to `secure_boot_enroll`.
  The build checks their structure and fails unless db holds, or holds an issuer of, the signer of every signed binary that the firmware or systemd-boot can start: the imported ones and binaries that were already signed, such as a distribution-signed systemd-boot or shim, whose embedded certificates may provide intermediates.
  Startable binaries are the `*.efi` files and the `linux` and `efi` files of `loader/entries/*.conf`; other files, such as a kernel that kernel-install left on the ESP, are not checked.
  For a shim chain, db must therefore also hold the vendor CA that signed the second stage, not only the CA that signed shim.
  It does not verify the PKCS#7 signatures of the `.auth` files, which the firmware checks during enrollment.
- Only the files of the ESP change.
  The GPT, the other partitions, and the FAT volume ID, label and geometry stay as built, so the result is deterministic for the same signed inputs.
- The rule returns DefaultInfo with the disk image and a JSON record of the changes, and the image's `MkosiImageInfo` with `raw_image` replaced, so `qemu_ovmf_boot_test` and install tooling accept it directly.

The action copies the multi-gigabyte image; it uses the image build's execution requirements and the mnemonic `SecureBootSignedImage`, so you can keep its output out of caches like the image itself, for example with `--modify_execution_info=SecureBootSignedImage=+no-cache`.

### Auto-enrollment on first boot

systemd-boot (systemd 257, as in Debian 13) enrolls `/loader/keys/auto/` only while the firmware is in Setup Mode (no PK enrolled) or Audit Mode.
It writes `db`, the optional `dbx`, `KEK` and finally `PK`, which takes the firmware out of Setup Mode, and then resets the machine; from the next boot on, the firmware only starts binaries that db trusts.

| `secure_boot_enroll` | Behavior |
| --- | --- |
| `if-safe` (default) | Enrolls automatically only inside a virtual machine; on hardware it adds a boot menu entry. |
| `force` | Also enrolls on hardware, after a 15-second countdown that a key press aborts. |
| `manual` | Adds a boot menu entry "Enroll Secure Boot keys: auto". |

Before using `force` on hardware:

- Some firmware cannot clear an enrolled PK from its setup UI, so a wrong key set can leave a device that boots nothing but your signed binaries, or nothing at all.
  Keep the PK private key: with it you can sign updates that rotate or remove the keys later.
- Add the Microsoft UEFI CA certificates (Microsoft Corporation UEFI CA 2011 and Microsoft UEFI CA 2023) to db unless you are sure that you do not need them.
  Option ROMs of plug-in graphics and network cards are signed with them, and without them a device may lose its display or network boot; they also keep shim-based rescue media bootable.
- Test the exact `.auth` files on the device model, and keep the firmware's recovery procedure at hand.

systemd-sysupdate never replaces systemd-boot: [update payloads](sysupdate-ab.md#update-payloads) carry only roots and UKIs, so the signed systemd-boot written at installation stays until you reinstall it.
Sign the UKIs of later releases with the same db key and ship them with `sysupdate_payload(signed_uki = ...)`.

### Releases that the firmware refuses

Once the keys are enrolled, ship every payload with `sysupdate_payload(signed_uki = ...)`, signed by a key that db trusts.
systemd-boot (systemd 257) bumps an entry's boot counter before `LoadImage`; when the firmware refuses the UKI, it logs `Error loading …: Access denied` and returns to the firmware instead of falling back to another entry.
Recovering then needs a reset: a hardware watchdog, firmware that falls through to another boot option, or a power cycle.

- With `boot_attempts = 1`, one reset suffices, because the refused release has no tries left and sorts last.
- With the default of 3 attempts, it takes three resets.
- A default that names the refused entry's exact ID (with `bootctl set-default` or `default` in `loader.conf`), or `default @saved`, keeps selecting it, so recovering needs console access to the boot menu.
  Glob defaults such as the default `*` recover, because entries without tries left sort last.

### Testing enrollment in QEMU

The toolchain's OVMF is built without Secure Boot, so it neither enrolls keys nor refuses unsigned binaries.
`qemu_ovmf_boot_test(secure_boot = True)` boots Debian's Secure Boot capable OVMF (`OVMF_CODE_4M.secboot.fd` with SMM and secure flash, from the pinned Debian 13 `ovmf` package) instead.
Its variable store starts empty, in Setup Mode, so systemd-boot enrolls the image's keys on the first boot; `machine_args` must select the `q35` machine.
Only tests that set `secure_boot` download this firmware.

```starlark
qemu_ovmf_boot_test(
    name = "os_secure_boot_test",
    allow_reboot = True,  # Enrollment resets the machine.
    image = ":os_installer",
    progress_markers = [
        "Custom Secure Boot keys successfully enrolled, rebooting the system now!",
        "EFI stub: UEFI Secure Boot is enabled.",
    ],
    secure_boot = True,
)
```

[`e2e/smoke`](../e2e/smoke/BUILD.bazel) `secure_boot_lifecycle_test` enrolls the keys of `secure_boot_ephemeral_test_fixture`, checks the `SecureBoot` and `SetupMode` EFI variables from release 1, updates to release 2 with a signed UKI, and expects the firmware to refuse the unsigned UKI of release 3.

The boot test's `<name>_config` target is always testonly, so a testonly image, such as one signed by `secure_boot_ephemeral_test_fixture` and marked testonly, boots without `testonly` on the test.

#### Configuring the guest under Secure Boot

Tests often configure the guest from outside the image, for example to start a unit that prints a readiness marker.
With Secure Boot enabled, these ways behave differently in systemd 257:

| Way | With Secure Boot |
| --- | --- |
| Boot loader options, such as `options` in a Type #1 entry or a command line edited in the systemd-boot menu | Ignored, because the UKI has a `.cmdline` section ([systemd-stub(7)][systemd-stub]). |
| SMBIOS Type 11 string `io.systemd.stub.kernel-cmdline-extra=` in `machine_args` | Appended to the kernel command line and measured into PCR 12; ignored only in confidential VMs ([systemd-stub(7)][systemd-stub-smbios], [`stub.c`][stub-c]). |
| SMBIOS credentials (`io.systemd.credential:` and `io.systemd.credential.binary:`), for example with `credentials` | Imported by the service manager; ignored only in containers and confidential VMs ([systemd.system-credentials(7)][system-credentials], [`import-creds.c`][import-creds]). |

`secure_boot_lifecycle_test` checks both SMBIOS ways with Secure Boot enabled.
`credentials` passes each entry as `io.systemd.credential:<name>=<value>` without restating `machine_args`.
A `systemd.unit-dropin.<unit>` credential adds a drop-in to a unit ([systemd-debug-generator(8)][debug-generator]), so a test can start a readiness unit that the image does not enable:

```starlark
qemu_ovmf_boot_test(
    name = "os_secure_boot_ready_test",
    allow_reboot = True,
    credentials = {
        "systemd.unit-dropin.multi-user.target": "[Unit]\nWants=os-ready.service\n",
    },
    image = ":os_installer",
    progress_markers = ["Custom Secure Boot keys successfully enrolled, rebooting the system now!"],
    readiness_marker = "os-ready: SecureBoot=1",
    secure_boot = True,
    stop_after_readiness = True,
)
```

Prefer markers that the image's units or the boot loader print over kernel messages.
`quiet` on the image's kernel command line lowers the log level of the kernel's EFI stub, which then no longer prints `EFI stub: UEFI Secure Boot is enabled.` ([`efi-stub-helper.c`][efi-stub-helper], [`secureboot.c`][efi-secureboot]).
systemd-boot prints `Custom Secure Boot keys successfully enrolled, rebooting the system now!` regardless, and a unit can report the `SecureBoot` EFI variable, as `secure_boot_lifecycle_test` does.

[systemd-stub]: https://www.freedesktop.org/software/systemd/man/257/systemd-stub.html#Description
[systemd-stub-smbios]: https://www.freedesktop.org/software/systemd/man/257/systemd-stub.html#io.systemd.stub.kernel-cmdline-extra
[stub-c]: https://github.com/systemd/systemd/blob/v257/src/boot/stub.c#L771-L800
[system-credentials]: https://www.freedesktop.org/software/systemd/man/257/systemd.system-credentials.html
[import-creds]: https://github.com/systemd/systemd/blob/v257/src/core/import-creds.c#L570-L600
[debug-generator]: https://www.freedesktop.org/software/systemd/man/257/systemd-debug-generator.html
[efi-stub-helper]: https://github.com/torvalds/linux/blob/v6.12/drivers/firmware/efi/libstub/efi-stub-helper.c#L75-L76
[efi-secureboot]: https://github.com/torvalds/linux/blob/v6.12/drivers/firmware/efi/libstub/secureboot.c#L60

## Trust boundary

| Protected against | Not protected against |
| --- | --- |
| A private key reaching any Bazel action, cache, remote executor, runfiles tree, log, or CI artifact. | A compromised external signer. |
| A substituted request, binary, signature, or certificate, including another binary signed by the trusted key. | Certificate issuance policy. |
| Malformed, duplicate, or trailing certificate data and transplanted certificate tables. | HSM operation or signer attestation. |

The request, certificate, unsigned and signed binaries, and verification metadata are public artifacts.
A transport envelope around them does not replace the embedded Authenticode check.

## Reproducibility

Unsigned images stay deterministic and cacheable.
Signed binaries depend on the signer (timestamps, certificate rotation) and are not reproducible; reproducibility manifests cover the unsigned image.

## Scope

Secure Boot applies only to UEFI release images: their UKIs and the PE/COFF binaries on their ESP.
The dm-verity root hash is embedded in the unsigned UKI before the request is created.
BIOS images cannot be signed.

`secure_boot_ephemeral_test_fixture` signs the UKIs and `esp_paths` of `images` with a short-lived db key for tests, and writes `PK.auth`, `KEK.auth` and `db.auth` for short-lived PK and KEK keys.
Use it as the `certificate` of the requests, the `signed_binary` of the imports and the `auto_enroll_keys` of `secure_boot_signed_image`; each import selects the fixture's binary that matches its request.
The keys never leave one uncached action that runs on the local machine, never remotely; never use them for production.
