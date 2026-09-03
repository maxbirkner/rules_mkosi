# Secure Boot and offline signing

`mkosi_image` remains unsigned by default. `unified_kernel_image = "unsigned"`
creates a deterministic UKI without accepting any key. Signing is separate:

1. `secure_boot_signing_request` hashes the unsigned UKI, records
   `authenticode-sha256`, its canonical request digest, the UEFI signing
   context, and the SHA-256 fingerprint of the expected public certificate in
   `mkosi-secure-boot-signing-request-v2` JSON.
   Certificate input is accepted only when it contains exactly one PEM or DER
   X.509 object; bundles, duplicates, reversed chains, and trailing data are
   rejected. The rule emits and subsequently uses one normalized certificate.
2. A signing system outside Bazel validates that request, Authenticode-signs
   the exact UKI, and returns the firmware-consumable signed PE/COFF image.
3. `secure_boot_import_response` validates PE and `WIN_CERTIFICATE` bounds,
   strictly decodes the PKCS#7 `SignedData` and `SpcIndirectDataContent`,
   requires exactly one SHA-256 digest algorithm and one RSA/SHA-256
   `SignerInfo`, cryptographically verifies the signer as the exact expected
   certificate, and compares the embedded image digest with an independently
   computed Authenticode PE hash. It also proves that stripping the certificate
   table while normalizing only the PE checksum and security-directory fields
   recovers the requested unsigned UKI.
   OpenSSL is given only the normalized certificate with `-nointern`, and the
   certificate it reports for the verified `SignerInfo` must have identical
   DER bytes and fingerprint.

The request, request digest, unsigned UKI, certificate, external signed UKI,
and verification metadata are public artifacts. A detached workflow envelope
may protect transport, but never substitutes for embedded Authenticode
verification. A production private key is never a rule attribute or action
input. The external signer is the trust boundary.

## Key custody and threats

The boundary prevents an ordinary Bazel action, remote executor, action cache,
runfiles tree, log, or CI artifact from receiving a production private key. It
detects substitution of the request, returned UKI, embedded signature, or
certificate, including a different valid UKI signed by the trusted key. It
rejects malformed, duplicate, out-of-bounds, or trailing certificate data. It
also rejects a certificate table transplanted from another same-layout UKI
signed by the trusted certificate. It does not protect a compromised offline
signer, validate certificate issuance
policy, operate an HSM, or attest signer hardware.

The ephemeral test fixture generates a one-day RSA key and Authenticode-signs
a real PE in one action. The key exists only below action-private scratch, is
overwritten and removed before exit, and is never an output, provider, input,
argument to another action, runfile, or metadata value. The action requires
`local`, `no-remote`, `no-remote-exec`, `no-remote-cache`, and `no-cache`. It
is for tests only, never production custody.

Unsigned release artifacts remain deterministic and cacheable. Signed UKIs
are external responses and can vary because of signing timestamps, certificate
rotation, or signer implementation; do not claim byte reproducibility for
them. Reproducibility manifests continue to describe the unsigned image graph.

BIOS images, rootfs payloads, dm-verity generation, and release network
isolation are unchanged. Secure Boot applies only to externally signed UEFI
UKIs; the dm-verity root hash remains linked into the unsigned UKI before the
request is created.
