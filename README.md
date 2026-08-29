# rules_mkosi

Bazel rules for assembling bootable Linux OS images with
[mkosi](https://github.com/systemd/mkosi).

The repository currently contains a host-independent hello-world
implementation. It exercises the intended Bazelmod extension, toolchain,
provider, rule, analysis-test, and consumer-test architecture without
requiring mkosi or image-building tools on the host.

## Try the skeleton

```starlark
bazel_dep(name = "rules_mkosi", version = "0.0.0")
local_path_override(module_name = "rules_mkosi", path = "/path/to/rules_mkosi")

mkosi = use_extension("@rules_mkosi//mkosi:extensions.bzl", "mkosi")
mkosi.toolchain()
use_repo(mkosi, "mkosi_toolchains")
register_toolchains("@mkosi_toolchains//:all")
```

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_image")

mkosi_image(
    name = "demo",
    distribution = "debian",
)
```

Development and test commands are documented once in
[CONTRIBUTING.md](CONTRIBUTING.md). The independent consumer module is
described in [`e2e/README.md`](e2e/README.md).

The current `mkosi_image` produces a deterministic text fixture rather than a
bootable image. Replacing this stub with a pinned mkosi executable and its
declared toolchain dependencies is the next implementation milestone.

Before adding an image action, run the explicitly sandboxed
`//mkosi/private:kernel_preflight_host_test` on the intended Linux execution
platform:

```console
bazel test -c opt --spawn_strategy=linux-sandbox \
  --test_strategy=exclusive --test_output=all \
  //mkosi/private:kernel_preflight_host_test
```

It reports each required namespace, procfs, sysctl, mapping, capability,
mount, and root-transition check and exits non-zero for an unqualified host.
See the
[host-kernel contract](docs/design/0004-host-kernel-contract.md).

## Design

The [design evaluations](docs/design/README.md) explain the selection of mkosi
and Debian, the Bazel boundary, testing strategy, and path to the Bazel Central
Registry.

## License

Apache-2.0. mkosi itself is LGPL-2.1-or-later and will retain its own license
when it becomes a downloaded toolchain component.
