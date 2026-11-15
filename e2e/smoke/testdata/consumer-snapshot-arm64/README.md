# Consumer arm64 snapshot lock fixture

`debian.spec.json` requests the arm64-only `arm-trusted-firmware` and the packages of the arm64 A/B update fixtures, which match the [release example's](../../example/debian.spec.json) with `linux-image-arm64`, on top of the Debian essential and required set, resolved for arm64.
Regenerate `debian.lock.json` from `e2e/smoke` with:

```console
bazel run //:consumer_arm64_debian_lock.update
```

`//:consumer_arm64_debian_lock_test` fails when the lock is stale for the specification.
