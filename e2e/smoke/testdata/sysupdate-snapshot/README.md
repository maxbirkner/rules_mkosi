# A/B update snapshot lock fixture

`debian.spec.json` locks the packages of the A/B release fixture, including
`systemd-container` for `systemd-sysupdate`, and the packages mkosi's default
Debian 13 initrd installs. Regenerate `debian.lock.json` from `e2e/smoke` with:

```console
bazel run //:sysupdate_debian_lock.update
```

`//:sysupdate_debian_lock_test` fails when the lock is stale for the specification.
