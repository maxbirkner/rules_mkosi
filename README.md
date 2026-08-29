# rules_mkosi

Bazel rules for assembling bootable Linux OS images with
[mkosi](https://github.com/systemd/mkosi).

The ruleset provides checksum-pinned mkosi v27, QEMU 11.0.0.1, and OVMF
`edk2-stable202605-r1` toolchains. QEMU binaries are supplied by
[rules_qemu](https://github.com/hermeticbuild/rules_qemu); this ruleset adds
the OVMF artifact and a small QEMU/OVMF provider and smoke-test wrapper.
The supported Bazel floor is 7.7.0 because that is the minimum declared by
rules_qemu 0.3.0.

## Configure the toolchain

```starlark
bazel_dep(name = "rules_mkosi", version = "0.0.0")
local_path_override(module_name = "rules_mkosi", path = "/path/to/rules_mkosi")

mkosi = use_extension("@rules_mkosi//mkosi:extensions.bzl", "mkosi")
mkosi.toolchain()  # Defaults to the pinned v27 toolchain.
use_repo(mkosi, "mkosi_toolchains")
register_toolchains("@mkosi_toolchains//:all")
```

`@mkosi_toolchains//:qemu_linux_x86_64` is constrained to Linux x86-64 and
provides `MkosiQemuToolchainInfo` through the
`//mkosi/toolchain:qemu_toolchain_type` toolchain. Its QEMU executable,
`qemu-img`, QEMU system data, `OVMF_CODE`, and `OVMF_VARS` are all runfiles;
tests do not use host QEMU or firmware. The extension also requires
`rules_qemu` and its QEMU extension:

```starlark
bazel_dep(name = "rules_qemu", version = "0.3.0")
qemu = use_extension("@rules_qemu//qemu/extension:qemu.bzl", "qemu")
use_repo(
    qemu,
    "qemu_img_prebuilt_linux_amd64",
    "qemu_system_bin_prebuilt_linux_amd64_x86_64_softmmu",
    "qemu_system_data_prebuilt_linux_amd64",
    "qemu_system_toolchains",
    "qemu_user_toolchains",
)
```

The QEMU system artifact is pinned by SHA-256
`b84d359893a0a1d565f368adb8290933ef9c99431acd98cff0fc4c9b35de3d22`
(`sha256-uE01mJOgodVl82ituCkJM++cmUMazZjP8PxMmzXePSI=`). OVMF is pinned by
SHA-256
`8ae4d2d73161cc2335f5675d3b8b6edfa0642301679764a246940488ea3ce20d`
(`sha256-iuTS1zFhzCM19WddO4tu36BkIwFnl2SiRpQEiOo84g0=`).

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
