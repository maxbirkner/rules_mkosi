# Secure Boot and offline signing

`mkosi_image` remains unsigned by default. `unified_kernel_image = "unsigned"`
creates a deterministic UKI without accepting any key. Signing is a separate
exchange:

1. `secure_boot_signing_request` hashes the unsigned UKI, records
   `rsa-pkcs1-sha256`, and binds the SHA-256 fingerprint of the expected public
   certificate in `mkosi-secure-boot-signing-request-v1` JSON.
2. A signing system outside Bazel validates that request, Authenticode-signs
   the UKI, and returns the signed UKI plus canonical
   `mkosi-secure-boot-signing-response-v1` JSON and a detached signature over
   that JSON.
3. `secure_boot_import_response` verifies the response signature, expected
   certificate, request digest, and returned UKI digest before exposing
   `SecureBootSignedUkiInfo`.

The request, unsigned UKI, certificate, external signed UKI, detached
signature, and verification metadata are public artifacts. A production
private key is never a rule attribute or action input. The external signer is
the trust boundary and must verify policy and produce a valid PE/COFF
Authenticode signature; this ruleset verifies exchange binding, not CA policy.

## Key custody and threats

The boundary prevents an ordinary Bazel action, remote executor, action cache,
runfiles tree, log, or CI artifact from receiving a production private key. It
detects substitution of the request, returned UKI, response signature, or
certificate. It does not protect a compromised offline signer, validate
certificate issuance policy, operate an HSM, or attest signer hardware.

Ephemeral test helpers generate one-day RSA keys and detached responses. Their
key-producing and signing actions require `local`, `no-remote`,
`no-remote-exec`, `no-remote-cache`, and `no-cache`; the private key is omitted
from `DefaultInfo`. They are for tests only, never production custody.

Unsigned release artifacts remain deterministic and cacheable. Signed UKIs
are external responses and can vary because of signing timestamps, certificate
rotation, or signer implementation; do not claim byte reproducibility for
them. Reproducibility manifests continue to describe the unsigned image graph.

BIOS images, rootfs payloads, dm-verity generation, and release network
isolation are unchanged. Secure Boot applies only to externally signed UEFI
UKIs; the dm-verity root hash remains linked into the unsigned UKI before the
request is created.
