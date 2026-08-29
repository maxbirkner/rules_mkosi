# rules_mkosi

Bazel rules for assembling bootable Linux OS images with
[mkosi](https://github.com/systemd/mkosi).

The ruleset provides a checksum-pinned mkosi v27 CLI and a Bazel-managed
Python 3.11 runtime. It exercises the Bazelmod extension, toolchain, provider,
rule, analysis-test, and consumer-test architecture without requiring host
Python or mkosi.

## Configure the toolchain

```starlark
bazel_dep(name = "rules_mkosi", version = "0.0.0")
local_path_override(module_name = "rules_mkosi", path = "/path/to/rules_mkosi")

mkosi = use_extension("@rules_mkosi//mkosi:extensions.bzl", "mkosi")
mkosi.toolchain()  # Defaults to the pinned v27 toolchain.
use_repo(mkosi, "mkosi_toolchains")
register_toolchains("@mkosi_toolchains//:all")
```

The supported toolchain versions are intentionally explicit:

| mkosi | Immutable source URL | SHA-256 |
| --- | --- | --- |
| 27 | `https://github.com/systemd/mkosi/archive/4736cd836108a97772142c461c49f1ddb4172348.tar.gz` | `fa34b3ba66cc71d202b267a0f55e6c77f41d8db273ea5404f7fad99e464835f8` |

The runtime uses only the Bazel-managed Python 3.11 standard library for
`mkosi --version`. The pinned `pefile` wheel is included for v27's bootable
PE inspection paths and is not obtained from the host environment.

The root module may select a version with `mkosi.toolchain(version = "27")`;
unsupported or conflicting requests fail during module resolution.

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

The current `mkosi_image` still produces a deterministic text fixture rather
than a bootable image. Image assembly and its host-capability contract are
later milestones.

Before adding an image action, run the explicitly sandboxed
`//mkosi/private:kernel_preflight_host_test` on the intended Linux execution
platform:

```console
bazel shutdown
bazel test --config=kernel_preflight \
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
