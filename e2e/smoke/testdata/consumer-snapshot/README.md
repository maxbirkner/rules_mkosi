# Consumer snapshot lock fixture

`debian.spec.json` requests one package from `non-free-firmware` on top of the
Debian essential and required set. Regenerate `debian.lock.json` from
`e2e/smoke` with:

```console
bazel run //:consumer_debian_lock.update
```

`//:consumer_debian_lock_test` fails when the lock is stale for the specification.
