# Consumer snapshot lock fixture

`debian.spec.json` requests one package from `non-free-firmware` on top of the
Debian essential and required set. Regenerate `debian.lock.json` from
`e2e/smoke` with:

```console
bazel run @rules_mkosi//mkosi/debian:generate_lock -- \
  --spec testdata/consumer-snapshot/debian.spec.json \
  --output testdata/consumer-snapshot/debian.lock.json
```
