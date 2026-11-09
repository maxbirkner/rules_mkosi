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

## Signing request schema

The request JSON (`<name>.secure-boot-request.json`) is an object with exactly these fields; a signer must reject any other field or value.

| Field | Value |
| --- | --- |
| `format_version` | `mkosi-secure-boot-signing-request-v3`. |
| `context` | `uefi-secure-boot-uki` when `esp_path` is empty, otherwise `uefi-secure-boot-esp-file`. |
| `esp_path` | Path of the binary on the ESP, such as `EFI/systemd/systemd-bootx64.efi`, or the empty string for the image's UKI. |
| `signature_algorithm` | `authenticode-sha256`: one embedded RSA PKCS #1 v1.5 Authenticode signature with SHA-256 digests. |
| `unsigned_sha256` | Lowercase hex SHA-256 of the unsigned binary file. |
| `certificate_sha256` | Lowercase hex SHA-256 of the signer certificate's DER encoding, as re-encoded by OpenSSL. |

`certificate_sha256` is the SHA-256 fingerprint of the certificate, the same as `openssl x509 -in db.crt -noout -fingerprint -sha256` without colons, in lower case; the request's `<name>.certificate.der` holds exactly the hashed bytes.
`<name>.secure-boot-request.sha256` holds the lowercase hex SHA-256 of the request serialized as compact JSON with sorted keys (`json.dumps(request, sort_keys=True, separators=(",", ":"))`) and a trailing newline.

## Signing in CI

`secure_boot_signing_manifest` lists requests for a signer that knows nothing about Bazel providers, and `@rules_mkosi//mkosi:secure_boot_signer` is a reference signer for it.

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "secure_boot_signing_manifest")

secure_boot_signing_manifest(
    name = "signing_manifest",
    requests = {
        ":os_signing_request": "os.efi",
        ":systemd_boot_signing_request": "systemd-bootx64.efi",
    },
)
```

`bazel build //:signing_manifest` writes `bazel-bin/signing_manifest.secure-boot-signing-manifest.json` and every file it names (`mkosi-secure-boot-signing-manifest-v1`):

```json
{
  "format_version": "mkosi-secure-boot-signing-manifest-v1",
  "requests": [
    {
      "certificate": "bazel-out/k8-fastbuild/bin/os_signing_request.certificate.der",
      "context": "uefi-secure-boot-uki",
      "esp_path": "",
      "label": "@@//:os_signing_request",
      "request": "bazel-out/k8-fastbuild/bin/os_signing_request.secure-boot-request.json",
      "request_digest": "bazel-out/k8-fastbuild/bin/os_signing_request.secure-boot-request.sha256",
      "signed_name": "os.efi",
      "unsigned_binary": "bazel-out/k8-fastbuild/bin/os.efi"
    }
  ]
}
```

- Entries are sorted by `signed_name`, the file name under which the signer returns the signed binary.
- Paths are relative to the execution root (`bazel info execution_root`); from the workspace they also resolve through the `bazel-out` convenience symlink.
- The manifest names the request files, not their contents: a signer reads and validates each request itself.

The reference signer runs outside Bazel actions, through `bazel run`, so the private key never enters Bazel:

```console
bazel build //:signing_manifest
manifest="$(realpath bazel-bin/signing_manifest.secure-boot-signing-manifest.json)"
bazel run @rules_mkosi//mkosi:secure_boot_signer -- \
  --manifest "$manifest" \
  --certificate keys/db.crt \
  --key "$XDG_RUNTIME_DIR/db.key" \
  --output-dir signed
```

Resolve the manifest's path right after building it, before `bazel run`.
`bazel run` builds the signer first and points the `bazel-bin` convenience symlink at the signer's configuration.
That configuration differs from the manifest's if the build used options that change the output directory, such as `-c opt`, or if the root module's default Python version is not the one that rules_mkosi builds the signer with.
`bazel-bin/signing_manifest.secure-boot-signing-manifest.json` then names a missing or stale manifest when the signer starts.

`bazel run --script_path=sign.sh @rules_mkosi//mkosi:secure_boot_signer` writes a script that runs the signer later without Bazel, for example in a separate CI step.
Relative paths are relative to the directory that `bazel run` was started in.
The execution root is the parent of `bazel-out` in the manifest's real path; pass `--execroot` if the manifest was copied elsewhere.

Before signing anything, the signer checks for every entry:

- the manifest and request schemas, the request digest, and that the request's `esp_path` and `context` match the manifest;
- that the unsigned binary is an unsigned PE/COFF file with the requested `unsigned_sha256`, so a substituted binary is rejected;
- that `--certificate` (PEM or DER) and the request's certificate both have the requested `certificate_sha256`;
- that a certificate in the `--key` file, if there is one, is `--certificate`.

It then signs each binary and, before writing anything to `--output-dir`, checks that the signed binary is the unsigned one plus one Authenticode signature by `--certificate` that verifies with its public key, which also detects a key that does not belong to the certificate.
`--validate-only` runs the checks without a key and signs nothing.

The private key is read in place by the signing tool; the signer never copies or prints it.
Keep it on a tmpfs such as `$XDG_RUNTIME_DIR` with mode `0600`, and remove it after signing.
The signer warns if other users can access the key file.

The signer uses the pinned `systemd-sbsign` of rules_mkosi's Debian tools by default, which runs in unprivileged user namespaces.
Where those are blocked outside Bazel's sandbox, for example by AppArmor on Ubuntu 24.04 (`kernel.apparmor_restrict_unprivileged_userns=1`), pass a host signing tool with `--sbsign sbsign` (sbsigntools) or `--sbsign /usr/lib/systemd/systemd-sbsign`; the import verifies the result the same way.

### Signing time

OpenSSL, which both signing tools use, adds the current time as the `signingTime` attribute of each signature, so by default signing the same binaries twice gives different signed binaries.
Pass `--signing-time` with a Unix time in seconds, or set `SOURCE_DATE_EPOCH`, to sign deterministically: the same manifest, key and signing time then give byte-identical signed binaries, and so identical signed disk images and checksums.
`--signing-time` takes precedence over `SOURCE_DATE_EPOCH`; without either, the signer signs at the current time.

```console
bazel run @rules_mkosi//mkosi:secure_boot_signer -- \
  --manifest "$manifest" \
  --certificate keys/db.crt \
  --key "$XDG_RUNTIME_DIR/db.key" \
  --output-dir signed \
  --signing-time "$(git log -1 --format=%ct)"
```

Use a time inside the certificate's validity, such as the commit time of the release.
The signer rejects a signing time before the certificate's `notBefore` or after its `notAfter`, before signing anything, because such a signature claims a time at which the certificate was not valid.
UEFI firmware ignores `signingTime`, so the choice does not affect booting.

The signing tool runs with its clock stopped at the signing time by [libfaketime](https://github.com/wolfcw/libfaketime): the pinned `systemd-sbsign` with the libfaketime of rules_mkosi's Debian tools, and a host tool through the `faketime` command, which must then be on `PATH` (Debian and Ubuntu package `faketime`).
The signer fails if a signature carries another `signingTime` than the requested one, for example because a statically linked tool ignored libfaketime.

### Scratch directory

The signer signs in a temporary directory under `--scratch`, which defaults to Python's temporary directory (`TMPDIR`, or `/tmp` if it is unset), and removes it when it finishes or fails.
For each request, the directory holds the certificate as PEM, the unsigned binary, and the signed binary, all of which are public; the binaries of every request stay there until all requests are signed.
The private key is never written there: a host signing tool gets its path, and the pinned `systemd-sbsign` reads it through a read-only bind mount.
While the pinned `systemd-sbsign` signs a request, the directory also holds an extracted copy of rules_mkosi's Debian tools, which runs from there.
Pass `--scratch` if `TMPDIR` lacks room for these files or does not allow running programs, for example a small or `noexec` tmpfs; with the pinned `systemd-sbsign`, its path must not contain `:`.

### Feeding signed binaries back

Keep the signer's output directory out of version control and select it with a flag, so default builds never depend on files that only CI produces:

```starlark
load("@bazel_skylib//rules:common_settings.bzl", "bool_flag")

bool_flag(
    name = "signed",
    build_setting_default = False,
)

config_setting(
    name = "use_signed_binaries",
    flag_values = {":signed": "True"},
)

secure_boot_ephemeral_test_fixture(
    name = "test_signer",
    esp_paths = ["EFI/systemd/systemd-bootx64.efi"],
    images = [":os"],
)

secure_boot_signing_request(
    name = "os_signing_request",
    certificate = select({
        ":use_signed_binaries": "db.crt",
        "//conditions:default": ":test_signer",
    }),
    image = ":os",
)

secure_boot_import_response(
    name = "os_signed_uki",
    request = ":os_signing_request",
    signed_binary = select({
        ":use_signed_binaries": "signed/os.efi",  # signed/ is in .gitignore.
        "//conditions:default": ":test_signer",
    }),
)
```

CI then runs `bazel build --//:signed //:signing_manifest`, the signer with `--output-dir signed`, and `bazel build --//:signed //:os_installer`.
Without the flag, the throwaway test signer answers the requests, so default builds and tests work without the production certificate or signed files.

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
- If the image derives its version with `image_version_from_inputs`, its `version_inputs` must list the certificate of every signed binary and the `auto_enroll_keys`, so that rotating them gives a new version; see [versions derived from the inputs](sysupdate-ab.md#versions-derived-from-the-inputs).
- Only the files of the ESP change.
  The GPT, the other partitions, and the FAT volume ID, label and geometry stay as built, so the result is deterministic for the same signed inputs.
- The ESP also gets `/loader/rules_mkosi-secure-boot.json`, an [ESP manifest](#image-metadata) of the signed binaries and the auto-enrollment keys, which systemd-boot ignores.
- The rule returns DefaultInfo with the disk image and a JSON record of the changes, and the image's `MkosiImageInfo` with `raw_image` replaced, so `qemu_ovmf_boot_test` and install tooling accept it directly.
  Like the one of `mkosi_image`, its `raw_image` output group holds only the disk image; `secure_boot_metadata` holds only the JSON record.

The action copies the multi-gigabyte image; it uses the image build's execution requirements and the mnemonic `SecureBootSignedImage`, so you can keep its output out of caches like the image itself, for example with `--modify_execution_info=SecureBootSignedImage=+no-cache`.

Select the disk image for upload or install tooling without a custom rule:

```starlark
filegroup(
    name = "os_installer_image",
    srcs = [":os_installer"],
    output_group = "raw_image",
)
```

On the command line, `bazel build //:os_installer --output_groups=raw_image` builds only the disk image.

### Image metadata

Install tooling can check, before it writes an image, that the image enrolls keys and that its db trusts the device's current signer, or refuse to write an image without keys to a device in Setup Mode.
The same facts are available in two places:

- `<name>.secure-boot-image.json`, the record in the `secure_boot_metadata` output group, with format `mkosi-secure-boot-signed-image-v2`.
- `/loader/rules_mkosi-secure-boot.json` on the ESP of the disk image, with format `mkosi-secure-boot-esp-manifest-v1`, so tools can read it from an image file, or from a freshly written device before its first boot, with the [ESP manifest reader](#reading-the-esp-manifest-of-a-disk-image) or any other FAT reader.
  Every signed image has it; an image without keys has empty `auto_enroll_keys`.

Both documents describe the image as built, and nothing updates the ESP manifest after the image is written:

- Once the device boots, systemd-boot renames boot-counted UKIs, for example `os_1+3.efi` to `os_1+2-1.efi`, and systemd-sysupdate installs newer UKIs and removes old ones, so `replaced` no longer matches the ESP.
  Match UKIs by `signed_sha256` rather than by `esp_path`.
- `auto_enroll_keys` are the keys that the image offers, not the keys that the firmware enrolled: systemd-boot enrolls them only in Setup Mode, depending on `secure_boot_enroll`.
  Read the `PK`, `KEK`, `db` and `dbx` EFI variables to learn what a device trusts.

| Field | Record | ESP manifest | Meaning |
| --- | --- | --- | --- |
| `format_version` | yes | yes | Schema of the document. |
| `auto_enroll_keys` | yes | yes | One object per `.auth` file in `/loader/keys/auto/`, in `PK`, `KEK`, `db`, `dbx` order; empty without `auto_enroll_keys`. |
| `secure_boot_enroll` | yes | yes | The `secure-boot-enroll` mode written to `loader.conf`, or `null` without keys. |
| `replaced` | yes | yes | One object per ESP file replaced by a signed binary, sorted by `esp_path`. |
| `changed_esp_paths` | yes | no | Every ESP file that the rule added or replaced, including the ESP manifest. |
| `esp_manifest` | yes | no | ESP path of the ESP manifest. |

An `auto_enroll_keys` object has `variable` (`PK`, `KEK`, `db` or `dbx`), `esp_path`, the file's `sha256` and `size` in bytes, `x509_sha256`, the SHA-256 fingerprints of the DER X.509 certificates in its signature lists in file order, and `signature_count`, the number of entries of all its signature lists, including hashes such as those in `dbx`.
A `replaced` object has `esp_path`, `unsigned_sha256`, `signed_sha256`, and `signer_sha256`, the SHA-256 fingerprint of the DER certificate that signed the binary.
Digests are lowercase hexadecimal; both documents are deterministic for the same inputs.
A new major `format_version` marks incompatible changes; fields may be added without one.

### Reading the ESP manifest of a disk image

`@rules_mkosi//mkosi:esp_manifest` prints the ESP manifest of a raw disk image, so install tooling can check the image before it writes it to a device:

```console
bazel run @rules_mkosi//mkosi:esp_manifest -- os_installer.raw
bazel run @rules_mkosi//mkosi:esp_manifest -- --list os_installer.raw
bazel run @rules_mkosi//mkosi:esp_manifest -- --extract loader/loader.conf os_installer.raw
```

It finds the only EFI system partition in the GPT and reads its FAT12, FAT16 or FAT32 file system itself, with 512- or 4096-byte sectors, so it needs neither root privileges, a loop device, nor mtools.
`--list` prints the path of every file on the ESP, and `--extract` writes the bytes of one file to standard output; paths are case-insensitive, as on FAT.
The exit status is 3 when the ESP lacks the file, for example the manifest of an image that `secure_boot_signed_image` did not build, and 1 when the image or the manifest is malformed, including a manifest with another `format_version`.

Python code in the build can depend on `@rules_mkosi//mkosi:esp_manifest_lib` instead:

```python
import rules_mkosi_esp_manifest

manifest = rules_mkosi_esp_manifest.read_esp_manifest("os_installer.raw")
trusted = {key["variable"]: key["x509_sha256"] for key in manifest["auto_enroll_keys"]}
```

`read_esp_manifest`, `read_esp_file`, `list_esp_files` and `find_esp` raise `EspFileNotFoundError` for a missing file and `InvalidImageError`, a `ValueError`, for a malformed image or manifest.

The library's only file is also the tool's standalone script, which uses only the Python standard library.
Install tooling that runs without Bazel can copy it and run it with any Python 3.10 or newer, for example on a freshly written device:

```console
script="$(bazel info output_base)/$(bazel cquery --output=files @rules_mkosi//mkosi:esp_manifest_lib)"
python3 "$script" /dev/sdX
```

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
Do not escape commas or line breaks in values: the rule doubles each comma, which QEMU reads as one literal comma, and line breaks reach the guest, so a value can hold a unit drop-in.
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
Signed binaries depend on the signer's key and certificate; reproducibility manifests cover the unsigned image.
The reference signer signs reproducibly with a [signing time](#signing-time), so a rebuild of a release with the same key gives the same signed binaries.

## Scope

Secure Boot applies only to UEFI release images: their UKIs and the PE/COFF binaries on their ESP.
The dm-verity root hash is embedded in the unsigned UKI before the request is created.
BIOS images cannot be signed.

`secure_boot_ephemeral_test_fixture` signs the UKIs and `esp_paths` of `images` with a short-lived db key for tests, at the `notBefore` time of its certificate, and writes `PK.auth`, `KEK.auth` and `db.auth` for short-lived PK and KEK keys.
Use it as the `certificate` of the requests, the `signed_binary` of the imports and the `auto_enroll_keys` of `secure_boot_signed_image`; each import selects the fixture's binary that matches its request.
The keys never leave one uncached action that runs on the local machine, never remotely; never use them for production.
