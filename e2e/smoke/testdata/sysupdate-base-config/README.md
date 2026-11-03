# A/B release base configuration fixture

This configuration tree is the version-independent part of the A/B releases.
`mkosi_base` installs its packages from the consumer-owned snapshot, applies
the lifecycle and transfer payloads, and archives the root together with
mkosi's default initrd. All three releases finalize the same base, so it is
built once.

The source date epoch is the snapshot time rather than zero so that
systemd-sysusers does not record a 1970 password change.
