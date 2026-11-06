# Release example

A complete release configuration of an immutable Debian 13 image, built only through rules_mkosi's [public API](../../../README.md#public-api):

- a consumer-owned Debian snapshot, locked with `debian_lock` and declared in [`MODULE.bazel`](../MODULE.bazel) as `@example_debian`;
- an offline, cacheable `release` build from that snapshot;
- an unsigned UKI and a zstd-compressed erofs root protected by dm-verity, in the first of two A/B slots;
- an assembled `mkosi_config_tree`, `mkosi_rootfs_payload` files, and `sysupdate_transfers`, so the image can install later releases;
- the release's `sysupdate_payload`, and a QEMU/OVMF boot test.

Run it from the consumer module:

```console
cd e2e/smoke
bazel test //example:all
```

The boot test passes when the image runs release `1` from the erofs root with dm-verity and powers off by itself.
`bazel build //example:example_os` builds the installable disk image, and `bazel build //example:example_os_payload` the update directory to publish.
After editing `debian.spec.json`, refresh the lock with `bazel run //example:debian_lock.update`; `//example:debian_lock_test` fails while it is stale.

To use it in your own module, copy this directory, add the [setup](../../../README.md#setup) to your `MODULE.bazel`, and declare the snapshot:

```starlark
debian_tools.snapshot(
    name = "example_debian",
    lock = "//example:debian.lock.json",
)
use_repo(debian_tools, "example_debian")
```

Then change `image_id`, the hostname, the update URL, the seed, and the packages.
For new releases, signing, and two-stage builds see [A/B updates](../../../docs/sysupdate-ab.md) and [Secure Boot](../../../docs/secure-boot.md).
