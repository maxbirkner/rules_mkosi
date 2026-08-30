# rules_mkosi

Bazel rules for assembling bootable Linux OS images with
[mkosi](https://github.com/systemd/mkosi).

The ruleset provides checksum-pinned mkosi v27, QEMU 11.0.0.1, and OVMF
`edk2-stable202605-r1` toolchains. QEMU binaries are supplied by
[rules_qemu](https://github.com/hermeticbuild/rules_qemu); this ruleset adds
the OVMF artifact and a small QEMU/OVMF provider and smoke-test wrapper.
The supported Bazel baseline is 8.5.1. The project follows a rolling policy
of supporting the current and previous Bazel LTS majors: Bazel 8 and 9.

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

The runtime uses a checksum-pinned, statically linked Python 3.11 runtime for
the Debian launcher and extractor. The pinned `pefile` wheel remains included
for v27's bootable PE inspection paths and is not obtained from the host
environment.

The Debian build-time userspace is pinned to Debian 13 (trixie), `amd64`,
and snapshot `20250814T000000Z`. The checked-in lockfile pins every package
URL, version, dependency edge, and SHA-256 digest. A repository fetches those
immutable `.deb` inputs, and a static-Python archive action builds the
deterministic tree without shell, compiler, or host archive tools. The
`@mkosi_debian_tools//:linux_x86_64` toolchain exposes the extracted
TreeArtifact, root-isolated launcher, and provenance through
`DebianToolsInfo`; image actions invoke the advertised launcher (a static
executable that starts the managed Python script) with the archive, extractor,
and digest as exact runfiles and an empty ambient `PATH`. The initial tracer set
includes APT/dpkg bootstrap tools, `systemd-repart`, filesystem and partition
utilities, GRUB/systemd-boot UEFI tools, `objcopy`, and their locked runtime
dependencies. Target image package acquisition remains out of scope.
Extraction uses that static Python runtime and preserves modes, merged-`/usr`
links, and in-root absolute links. Before any dynamic Debian ELF runs, the
static launcher and static namespace runner establish the user, mount, PID,
IPC, and UTS namespaces, pivot into the extracted root, and detach the host
root. Only then is the packaged Debian loader used for the requested tool;
the packaged bubblewrap binary is retained as a pinned package input but is
not used as a pre-isolation bootstrap.
The runner requires an empty supplementary-group list: it clears groups while
still permitted to do so and fails closed before entering the namespace when
the caller's groups cannot be cleared.
The lockfile's package SHA-256 values are the immutable download trust roots.
Package-index signature verification is intentionally not advertised because
the resolver does not currently perform that check.
The launcher intentionally leaves the network namespace shared: Bazel's
declared network policy is the authority for mkosi's target-package
acquisition. Issue #6 isolates the packaged filesystem and runtime state,
rather than silently forcing offline execution; the TLS regression is offline
in the sense that it verifies the deterministic packaged CA bundle without
contacting a server.

The default `.bazelversion` is Bazel 8.5.1, matching the checked-in Bzlmod
lockfile format. CI runs the root and independent consumer suites on pinned
Bazel 8.5.1 and 9.2.0. Bazel 8.5.1 uses `--lockfile_mode=error`; Bazel 9
uses `--lockfile_mode=off` only for compatibility commands because it uses a
newer lockfile format. CI never rewrites committed lockfiles.

The module has a normal dependency on the maintained
`hermetic_cc_toolchain` 4.3.0. The repository root registers its generic Linux
amd64 musl `@zig_sdk//toolchain:linux_amd64_musl` toolchain as the bootstrap
default; an independent downstream root opts into the same maintained
extension and registration (as shown by `e2e/smoke`) without setting
`--platforms` or `--host_platform`. Bzlmod requires that extension-provided
repositories be opted into by the downstream root module, so the maintained
dependency, extension, and registration are part of the documented consumer
setup rather than hidden development-only state. This is not a custom compiler
mechanism. The bootstrap targets use ordinary `cc_binary` toolchain resolution
with `fully_static_link`, and a consumer's root-module registration takes
precedence when it provides another compatible standard C/C++ toolchain.
rules_mkosi does not download, invoke, or select a raw compiler itself. The
resolved action graph and static ELF metadata are checked in CI.

For a consumer that overrides the default, register a compatible
`@bazel_tools//tools/cpp:toolchain_type` toolchain for Linux x86-64 and static
linking. The default registration is deliberately generic for normal Linux
x86-64 target and execution platforms, so unrelated consumer targets are not
silently transitioned to a musl platform. The maintained toolchain's own
constraints prevent the bootstrap binaries from being scheduled on another
operating system or CPU architecture.

The root module may select a version with `mkosi.toolchain(version = "27")`;
unsupported or conflicting requests fail during module resolution.

Consumers that need the Debian contract can import `DebianToolsInfo` from the
public `@rules_mkosi//mkosi:defs.bzl` label (or the compatibility wrapper
`@rules_mkosi//mkosi:debian_tools.bzl`). The canonical repository name remains
`mkosi_debian_tools` after the Debian extension is used.

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_image")

mkosi_image(
    name = "demo",
    config = "mkosi.conf",
)
```

Development and test commands are documented once in
[CONTRIBUTING.md](CONTRIBUTING.md). The independent consumer module is
described in [`e2e/README.md`](e2e/README.md).

`mkosi_image` declares a single `<name>.raw` output and consumes one mkosi
configuration file. It invokes the pinned mkosi v27 executable and the
extracted Debian 13 tools tree through their registered toolchains, with an
empty ambient `PATH`; no host executable lookup or shebang launcher is used.
The configuration label is mandatory and must resolve to exactly one file;
invalid file targets fail during Bazel analysis.
The rule overrides config output settings to `Format=disk`, `OutputExtension=raw`,
`CompressOutput=none`, and no split artifacts, so custom formats and redirected
outputs are not part of this tracer contract. The minimal tracer configuration
may acquire target Debian packages over the network, so the action is
explicitly non-cacheable, does not use remote execution, and requires a Linux
x86-64 execution platform with the namespace and mount capabilities in the
host-kernel contract. It is not an offline or remote-execution-hermetic action.

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
