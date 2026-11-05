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

`secure_boot_ephemeral_test_fixture` signs the UKIs and `esp_paths` of `images` with a short-lived key for tests.
Use it as both the `certificate` of the requests and the `signed_binary` of the imports; each import selects the fixture's binary that matches its request.
The key never leaves one local, uncached action; never use it for production.
