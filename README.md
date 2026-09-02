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

The zero-configuration mkosi toolchain uses the Python 3.14 line supplied by
the pinned `rules_python` 1.7.0 dependency (currently CPython 3.14.0). The
generated toolchain resolves `@rules_python//python:toolchain_type` instead of
embedding an interpreter label. A downstream root may therefore register its
own in-build CPython 3.14 toolchain at normal Bazel root-module precedence:

```starlark
# The target must provide a Python 3.14 PyRuntimeInfo with an interpreter
# artifact, its complete files, and interpreter_version_info.
register_toolchains("//toolchains:python_3_14")
```

Host `interpreter_path` runtimes are rejected: image actions require a declared
interpreter artifact and complete runtime closure. The Python major/minor must
remain 3.14 because mkosi and its locked wheels are tested as one runtime
contract. `MkosiToolchainInfo.python_version` reports that compatibility line;
`resolved_python_version` and `resolved_python_interpreter` identify the
selected concrete toolchain for diagnostics. No Python registration is needed
when accepting the default.

The Debian launcher has a separate requirement. It uses checksum-pinned,
statically linked CPython 3.14.7 because it must start before the isolated
Debian root or any dynamic loader is available. Consumers do not override this
security bootstrap. The native `@mkosi_debian_tools//:launcher` is a narrow,
fully static ELF entrypoint: the maintained rules_cc runfiles library locates
that interpreter and a generated Python launcher stub, inherited Python/loader
injection and signal state are cleared, and the interpreter is executed
directly with `-I`. The stub's host shebang is never executed.

All option parsing, archive/runfile selection, authentication, extraction, and
typed mount orchestration live in `debian_launcher.py`. Its public command is a
Click 8.5.0 CLI supplied through the locked `mkosi_pypi` repository. Click and
the Python runfiles library are present in the generated launcher's normal and
manifest runfiles, so neither `/usr/bin/env` nor host `PATH` is involved.
`--help` succeeds with status 0, usage errors use Click's status 2 diagnostics,
setup failures retain the `Debian launcher setup failed:` prefix and status 1,
and an invoked Debian tool's status is propagated unchanged. The pinned
`pefile` wheel remains included for v27's bootable PE inspection paths and is
not obtained from the host environment.

The Debian build-time userspace is pinned to Debian 13 (trixie), `amd64`,
and snapshot `20250814T000000Z`. The checked-in lockfile pins every package
URL, version, dependency edge, and SHA-256 digest. A repository fetches those
immutable `.deb` inputs, and a static-Python archive action builds the
deterministic tree archive without shell, compiler, or host archive tools. The
`@mkosi_debian_tools//:linux_x86_64` toolchain exposes that archive, a
compatibility TreeArtifact, the root-isolated launcher, and provenance through
`DebianToolsInfo`. Image actions transport the regular archive through Bazel's
cache boundary and extract it into action-local workspace storage before
invoking the pinned mkosi Python entrypoint with its managed Python runtime,
package dependencies, and an empty ambient `PATH`. The initial tracer set
includes APT/dpkg bootstrap tools, `systemd-repart`, filesystem and partition
utilities, GRUB/systemd-boot UEFI tools, `objcopy`, and their locked runtime
dependencies. Target image package acquisition remains out of scope.
Extraction uses the static Python bootstrap and preserves modes, merged-`/usr`
links, and in-root absolute links. Before any dynamic Debian ELF runs, the
static launcher and static namespace runner establish the user, mount, PID,
IPC, and UTS namespaces, pivot into the extracted root, and detach the host
root. Only then is the packaged Debian loader used for the requested tool;
the packaged bubblewrap binary is retained as a pinned package input but is
not used as a pre-isolation bootstrap.
The runner requires an empty supplementary-group list: it clears groups while
still permitted to do so and fails closed before entering the namespace when
the caller's groups cannot be cleared.
Typed input, workspace, and output binds require Linux 5.12 or newer and use
`open_tree(parent_fd, name, OPEN_TREE_CLONE)`, `fstat` validation,
`mount_setattr(detached_fd, "", AT_EMPTY_PATH | AT_RECURSIVE)` for read-only
binds, and `move_mount(detached_fd, "", ..., MOVE_MOUNT_F_EMPTY_PATH)`; after
that initial pin, the runner never re-resolves a source or destination pathname
for security-critical validation and uses no compatibility fallback.
The lockfile's package SHA-256 values are the immutable download trust roots.
Package-index signature verification is intentionally not advertised because
the resolver does not currently perform that check.

The lockfile also pins the signed `InRelease`, detached `Release.gpg`, and
compressed `Packages.xz` metadata. The snapshot repository rule downloads
these files with Bazel's content-addressed repository downloader; the build
action verifies the clear-signed `InRelease` with Debian's pinned archive
keyring, checks that it authenticates the separately pinned `Release`, verifies
the `Packages.xz` hash listed by that Release, and checks every locked package
record before staging it. Invalid signatures, changed metadata, duplicate
records, and unsafe package paths fail closed.
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

The extension also exposes `@mkosi_debian_snapshot//:repository`. This target
provides `DebianSnapshotInfo` and a deterministic local APT tree rooted at
`dists/trixie`, with locked packages under their original `pool/` paths:

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "DebianSnapshotInfo")

debian_repository = "@mkosi_debian_snapshot//:repository"
```

The repository rule performs network fetches only while Bazel resolves the
extension. The staging action itself has only downloaded metadata, locked
packages, the managed Python runtime, and the Debian toolchain as inputs; it
does not invoke apt, dpkg, curl, gpg, or host filesystem tools. This mirror is
the stable input boundary for `mkosi_image` release mode. The lock is an
explicitly selected representative Debian tools closure, not a general
dependency solver.

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_image")

mkosi_image(
    name = "demo",
    config = "mkosi.conf",
)
```

Legacy BIOS is an explicit release-only x86-64 compatibility tier:

```starlark
mkosi_image(
    name = "bios_release",
    config_tree = ":release_config",
    mode = "release",
    firmware = "bios",
    debian_snapshot = "@mkosi_debian_snapshot//:repository",
    release_seed = "00000000-0000-4000-8000-000000000015",
    release_source_date_epoch = 0,
)
```

This selects mkosi v27's `BiosBootloader=grub`, uses the pinned GRUB i386-pc
modules, and requires one GPT BIOS boot partition of at least 1 MiB. BIOS mode
rejects non-amd64 snapshots and UKI or Secure Boot settings. It disables the
UEFI bootloader for this explicitly selected tier.
It does **not** provide the authenticated UKI/Secure Boot/measured-boot chain
available to UEFI designs. Treat it as a weaker compatibility boundary; this
mode does not claim SeaBIOS or physical-hardware qualification.

The explicit `mode` attribute selects image-build policy. The default
`"tracer"` mode preserves the existing networked behavior and is intentionally
non-cacheable. A `"release"` image requires the authenticated snapshot target;
it stages that content-addressed mirror as mkosi's sole APT source and blocks
the action network namespace:

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_config_tree", "mkosi_image")

mkosi_config_tree(
    name = "release_config",
    src = "mkosi-release",
)
mkosi_image(
    name = "release",
    config_tree = ":release_config",
    mode = "release",
    debian_snapshot = "@mkosi_debian_snapshot//:repository",
    release_seed = "00000000-0000-4000-8000-000000000015",
    release_source_date_epoch = 0,
)
```

Release mode requires a declared `mkosi_config_tree`, resolves that
configuration with pinned mkosi, and rejects filesystem paths outside the
staged declared inputs. It also rejects a configuration unless `Seed=` and
`SourceDateEpoch=` exactly match `release_seed` and
`release_source_date_epoch`, and resolves Debian distribution, codename, and
snapshot defaults from `debian_snapshot`. It supplies fixed passwd, group, hosts, and NSS
files instead of importing host `/etc` state. With those declared
configuration/source inputs, the pinned mkosi and Debian toolchains, and the
authenticated snapshot repository, a release action may use Bazel's local and
remote action caches. It deliberately keeps `no-remote-exec`, because a remote
execution platform has not yet been qualified for the required Linux namespace
and mount contract. There is no fallback to a network mirror: a missing locked
package or attempted network access fails the action. Release images that
install APT do not retain a mutable package-source configuration; consume a
new declared snapshot to produce an updated release image.

To retain that cache guarantee, release mode rejects proxies, lifecycle scripts,
`ExtraTrees`, host microcode, and host kernel-module selection: those may
otherwise import host state or restore an APT source after the offline package
installation. Use a new immutable
configuration/source-tree input and a new release image for such changes.
Release configurations also reject `[Match]` and `[TriggerMatch]` sections,
because mkosi evaluates their host probes before configuration resolution.
They also reject mkosi incremental mode, so no untracked workspace cache can
influence a release artifact.

For a complete mkosi configuration directory, mark the exported directory
with `mkosi_config_tree`. The directory must contain `mkosi.conf`; mkosi's
relative `mkosi.conf.d/`, `mkosi.profiles/`, and `mkosi.extra/` paths are
preserved. Declared build source directories are marked with
`mkosi_source_tree` and mapped explicitly so their paths match `BuildSources`:

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_config_tree", "mkosi_image", "mkosi_source_tree")

mkosi_config_tree(name = "mkosi_config", src = "mkosi")
mkosi_source_tree(
    name = "project_sources",
    src = "src",
    executable_paths = ["mkosi.build"],
)
mkosi_image(
    name = "demo",
    config_tree = ":mkosi_config",
    source_trees = {"src": ":project_sources"},
)
```

`source_trees` keys are normalized relative paths and values must be
`mkosi_source_tree` targets. Absolute paths, `..` traversal, duplicate
sources, overlapping destinations, and manifest collisions with configuration
content are rejected before staging writes. Source-tree roles are checked again
at execution, including generated artifacts whose Bazel metadata is ambiguous.
Staging and materialization normalize files and directories to deterministic
timestamps and permissions, retaining only executable semantics; valid relative
symlinks are preserved. `executable_paths` explicitly identifies scripts that
must retain executable mode. This explicit mapping also works for labels from
external repositories and avoids relying on repository-relative runfiles paths.
A single-file `config` remains supported unchanged; when source trees are
supplied, that file is staged at its basename and selected with `-I`.

Image content that is not build source belongs in a typed rootfs payload:

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_rootfs_payload")

mkosi_rootfs_payload(
    name = "app",
    src = ":generated_appimage",
    destination = "/usr/local/bin/app",
    executable_paths = [""],
)
mkosi_rootfs_payload(
    name = "site",
    src = ":generated_site_tree",
    destination = "/opt/site",
    executable_paths = ["bin/start"],
)
# Add both labels to mkosi_image(rootfs_payloads = [...]).
```

Destinations are normalized absolute image paths; they never name host paths.
Payload files and tree contents are staged under `mkosi.extra`, so they compose
with static configuration content while duplicate, ancestor/descendant,
file/directory, source-alias, traversal, dangling-link, and escaping-link
conflicts fail closed. Files become root-owned mode 0644 (0755 only when
declared executable), directories mode 0755, and timestamps epoch zero.
Relative symlinks contained in trees are retained. Arbitrary ownership is not
currently modeled, so payloads must not claim non-root ownership.

Common declarative payloads map a unit to
`/usr/lib/systemd/system/example.service`, an executable binary or AppImage to
`/usr/local/bin/example`, sysusers and tmpfiles definitions to
`/usr/lib/sysusers.d/example.conf` and `/usr/lib/tmpfiles.d/example.conf`,
an `/etc/skel` tree to `/etc/skel`, and user defaults to a subdirectory such
as `/etc/skel/.config/example`. Use sysusers plus tmpfiles to create users and
home directories. Do not put credentials or secrets in payloads, and do not
replace these declarations with release lifecycle scripts.

Development and test commands are documented once in
[CONTRIBUTING.md](CONTRIBUTING.md). The independent consumer module is
described in [`e2e/README.md`](e2e/README.md).

`mkosi_image` consumes either one mkosi configuration file through `config` or
one explicitly typed configuration tree through `config_tree`. It invokes the
pinned mkosi v27 executable and the extracted Debian 13 tools tree through
their registered toolchains. The Debian tree crosses Bazel's
content-addressed cache as an authenticated tar file and is materialized only
inside the image action, preserving merged-`/usr` symlinks without exposing a
symlink-rich directory artifact to cache replay. The action uses an empty
ambient `PATH`; no host executable lookup or shebang launcher is used.
The configuration label is mandatory and must resolve to exactly one file;
invalid file targets fail during Bazel analysis.

### `MkosiImageInfo` output contract

`mkosi_image` returns the public `MkosiImageInfo` provider. Select a specific
artifact from this provider rather than identifying an artifact from a suffix,
basename, or the contents of `DefaultInfo`.

| Field | Type | Availability |
| --- | --- | --- |
| `format_version` | `string` | Always `mkosi-image-v1`. It identifies the stable provider contract. |
| `firmware` | `string` | Explicit `uefi` (default) or `bios` tier; never inferred from filenames. |
| `raw_image` | `File` or `None` | Present for the current disk/raw output mode. |
| `manifest` | `File` or `None` | `None` until a mode explicitly requests mkosi manifest output. |
| `partition_metadata` | `File` or `None` | Validated, normalized GPT JSON for release images; `None` in tracer mode. |
| `uki` | `File` or `None` | `None` until a mode produces a Unified Kernel Image. |
| `build_metadata` | `File` or `None` | Present for every current target. It is normalized JSON with schema `mkosi-image-build-metadata-v2`, output-role booleans, mode, and forced mkosi disk/raw/no-compression settings. Release metadata additionally records the authenticated snapshot identity, lock digest, and resolved reproducibility inputs. |
| `image` | `File` or `None` | Deprecated compatibility alias for `raw_image`; it is exactly the same artifact. New consumers must use `raw_image`. |

`DefaultInfo.files` contains each non-`None` artifact field once; its depset
iteration order is not an API. Today that is `raw_image` and `build_metadata`.
Future manifest, partition, or UKI modes will add their non-`None` artifacts
without changing the provider field meanings. This intentionally changes the
old singleton `DefaultInfo` projection: consumers that assumed its sole file
was the raw disk must migrate to `MkosiImageInfo.raw_image`. The retained
`image` field preserves source compatibility for existing provider consumers.
This contract defines output roles only; it does not generate UKIs, verity
artifacts, or partition metadata.

The provider stays at `mkosi-image-v1`: the metadata schema independently
advanced from v1 to v2 to make cache-relevant release provenance explicit.
Consumers must select the metadata artifact through `build_metadata` and use
its schema version when parsing its contents.

`qemu_ovmf_boot_test` is the reusable public boot-test adapter:

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "qemu_ovmf_boot_test")

qemu_ovmf_boot_test(
    name = "demo_boot_test",
    image = ":demo",
    readiness_marker = "systemd[1]: Hostname set to <demo>.",
)
```

It accepts an `mkosi_image` target and selects
`MkosiImageInfo.raw_image` explicitly. It resolves QEMU and OVMF through the
registered toolchain, runs QEMU with TCG,
no default devices, and a read-only snapshot of the image, then requires exact
serial readiness and guest shutdown markers. QMP, launch, firmware, guest,
readiness-timeout, and shutdown failures are reported separately with bounded
deadlines and retained serial/QEMU diagnostics. The state machine is
firmware-neutral; only this adapter supplies OVMF flash arguments. Machine
arguments and all deadlines/diagnostic retention are attributes so a future
SeaBIOS adapter can reuse the lifecycle. The `timeout` argument is a finite
Bazel test-timeout category (`"short"`, `"moderate"`, or `"long"`), defaulting
to `"moderate"` (300 seconds); `"eternal"` is deliberately rejected. The QMP,
boot, and shutdown deadlines must be positive and, together with a reserved
30-second cleanup/diagnostic margin, fit within the selected category
(`60`, `300`, or `900` seconds). Invalid categories or deadline combinations
fail during analysis, so a lifecycle timeout reports its own diagnostic before
Bazel's test deadline can terminate the process.
The `config` label remains compatible with existing consumers and must resolve
to exactly one file; typed tree targets are validated at analysis and again by
the staging preflight.
The rule overrides config output settings to `Format=disk`, `OutputExtension=raw`,
`CompressOutput=none`, and no split artifacts, so custom formats and redirected
outputs are not part of this tracer contract. The minimal tracer configuration
may acquire target Debian packages over the network, so its action is
explicitly non-cacheable, does not use remote
execution, and requires a Linux x86-64 execution platform with the namespace
and mount capabilities in the host-kernel contract. It is not an offline or
remote-execution-hermetic action. Release mode removes only the tracer's
network and no-cache restrictions; it remains local-execution-only until a
remote platform is qualified.

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
