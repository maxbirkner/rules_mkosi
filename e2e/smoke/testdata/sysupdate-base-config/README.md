# A/B release base configuration fixture

The version-independent part of the A/B releases: `mkosi_base` installs its packages from the consumer-owned snapshot and applies the lifecycle and transfer payloads.
All three releases finalize this one base.

The source date epoch is the snapshot time rather than zero so that systemd-sysusers does not record a 1970 password change.
