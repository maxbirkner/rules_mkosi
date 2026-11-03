# Secure Boot and offline signing

rules_mkosi never handles a production signing key.
`mkosi_image(unified_kernel_image = "unsigned")` builds a deterministic, cacheable unsigned UKI; a signer outside Bazel signs it, and Bazel verifies the result.

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
    signed_uki = "signed/os.efi",  # Returned by the external signer.
)
```

1. `secure_boot_signing_request` outputs the unsigned UKI, the normalized certificate, and a JSON request (`mkosi-secure-boot-signing-request-v2`) that binds the UKI digest, the `authenticode-sha256` algorithm, and the certificate fingerprint.
   It returns `SecureBootSigningRequestInfo`.
2. The external signer validates the request, Authenticode-signs exactly that UKI, and returns the signed PE file.
3. `secure_boot_import_response` accepts the signed UKI only if it carries exactly one RSA/SHA-256 Authenticode signature by the expected certificate and removing that signature (with the PE checksum and certificate-table fields it changes) yields exactly the requested UKI.
   It returns `SecureBootSignedUkiInfo` with `signed_uki` and verification metadata.

Pass the import target as `sysupdate_payload(signed_uki = ...)` to ship the signed UKI in an [A/B update](sysupdate-ab.md#update-payloads).

## Trust boundary

| Protected against | Not protected against |
| --- | --- |
| A private key reaching any Bazel action, cache, remote executor, runfiles tree, log, or CI artifact. | A compromised external signer. |
| A substituted request, UKI, signature, or certificate, including another UKI signed by the trusted key. | Certificate issuance policy. |
| Malformed, duplicate, or trailing certificate data and transplanted certificate tables. | HSM operation or signer attestation. |

The request, certificate, unsigned and signed UKIs, and verification metadata are public artifacts.
A transport envelope around them does not replace the embedded Authenticode check.

## Reproducibility

Unsigned images stay deterministic and cacheable.
Signed UKIs depend on the signer (timestamps, certificate rotation) and are not reproducible; reproducibility manifests cover the unsigned image.

## Scope

Secure Boot applies only to UEFI UKIs.
The dm-verity root hash is embedded in the unsigned UKI before the request is created.
BIOS images cannot be signed.

`secure_boot_ephemeral_test_fixture` signs a UKI with a short-lived key for tests.
The key never leaves one local, uncached action; never use it for production.
