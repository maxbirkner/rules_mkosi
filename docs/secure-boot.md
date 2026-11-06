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
bazel run @rules_mkosi//mkosi:secure_boot_signer -- \
  --manifest bazel-bin/signing_manifest.secure-boot-signing-manifest.json \
  --certificate keys/db.crt \
  --key "$XDG_RUNTIME_DIR/db.key" \
  --output-dir signed
```

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
Temporary files, which are public, go to a directory under `--scratch` or `TMPDIR`.

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
