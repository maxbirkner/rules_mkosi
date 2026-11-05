# rules_mkosi

Bazel rules for building bootable Linux OS images with [mkosi](https://github.com/systemd/mkosi) and testing them in QEMU.

- Pinned, checksum-verified toolchains: mkosi v27.1, a Debian 13 build-time userspace, QEMU, OVMF, and SeaBIOS.
  Image actions use no host executables.
- An uncached `tracer` mode for iteration and an offline, cacheable `release` mode built from an authenticated Debian snapshot.
- Unsigned UKIs, dm-verity, offline Secure Boot signing, and A/B updates with `systemd-sysupdate`.
- Boot tests that start an image under QEMU with UEFI or legacy BIOS firmware.

## Requirements

| Requirement | Supported |
| --- | --- |
| Bazel | 8 and 9 (the current and previous LTS majors). The minimum is 8.8.2. |
| Execution platform | Linux x86-64, kernel 5.12 or newer, unprivileged user and mount namespaces under Bazel's Linux sandbox (see [host-kernel contract](docs/design/0004-host-kernel-contract.md)). |
| Bazel server | Started without supplementary groups (see [below](#run-bazel-without-supplementary-groups)). |
| Images | Debian 13 (trixie), amd64. |
| KVM | Optional; boot tests fall back to TCG. |

Image actions never run remotely (`no-remote-exec`).
mkosi runs with `MKOSI_FORCE_USERNS_FALLBACK=1`, so it creates its own unprivileged user namespace instead of asking the host's `systemd-nsresourced`, and builds behave the same on every host.
As a consequence, `ForeignUIDRange=yes` is not supported and fails the build.

| Toolchain | Version |
| --- | --- |
| mkosi | 27.1 (`systemd/mkosi@ecf7f5702bb2052b7a69cab3fe7d37bc3b9ad77b`) |
| Python for mkosi | 3.14, from rules_python |
| Debian tools and snapshot | Debian 13, snapshot `20260912T080811Z` |
| QEMU | 11.0.0.1, from [rules_qemu](https://github.com/hermeticbuild/rules_qemu) |
| OVMF | `edk2-stable202605-r1` |
| SeaBIOS | `rel-1.17.0-0-gb52ca86e094d-prebuilt.qemu.org` |

Supported mkosi versions: 27.1 only, pinned to the commit above.
Release builds fail if mkosi differs from the version rules_mkosi was verified with, so newer mkosi releases need a rules_mkosi update.

## Setup

rules_mkosi is published to the [Bazel Central Registry](https://registry.bazel.build/modules/rules_mkosi).
Add to the root `MODULE.bazel`, using the latest version from the [releases](https://github.com/maxbirkner/rules_mkosi/releases):

```starlark
bazel_dep(name = "rules_mkosi", version = "0.1.0")

# Static C/C++ toolchain for rules_mkosi's bootstrap executables. Its extension
# reads only the root module's tags, so the root module must opt in.
bazel_dep(name = "hermetic_cc_toolchain", version = "4.3.0")
hermetic_cc = use_extension("@hermetic_cc_toolchain//toolchain:ext.bzl", "toolchains")
hermetic_cc.exec_platform(arch = "amd64", os = "linux")
use_repo(hermetic_cc, "zig_sdk")
register_toolchains("@zig_sdk//toolchain:linux_amd64_musl")

# QEMU binaries used by the mkosi toolchain repository.
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

# Optional: pin the mkosi version (default "27.1").
mkosi = use_extension("@rules_mkosi//mkosi:extensions.bzl", "mkosi")
mkosi.toolchain(version = "27.1")

# Built-in Debian snapshot and optional consumer-owned snapshots.
debian_tools = use_extension("@rules_mkosi//mkosi/debian:extensions.bzl", "debian_tools")
use_repo(debian_tools, "mkosi_debian_snapshot")
```

rules_mkosi registers its own mkosi, QEMU, and Debian tools toolchains.
The musl registration does not change the platform of your other targets.
Unsupported or conflicting mkosi versions fail during module resolution, and only the root module may set the toolchain `name`.

To use an unreleased commit, keep the `bazel_dep` and add an override:

```starlark
git_override(
    module_name = "rules_mkosi",
    commit = "<commit>",
    remote = "https://github.com/maxbirkner/rules_mkosi.git",
)
```

### Run Bazel without supplementary groups

Image builds refuse to run with supplementary groups, and an unprivileged process cannot drop them.
Start the Bazel server from a group-free identity; shut down a running server first because it keeps its groups:

```console
bazel shutdown
sudo -n setpriv --reuid="$(id -u)" --regid="$(id -g)" --clear-groups \
  env HOME="$HOME" PATH="$PATH" USER="$USER" bazel build //...
```

## Quick start

`mkosi.conf`:

```ini
[Distribution]
Distribution=debian
Release=trixie
Snapshot=20260912T080811Z

[Output]
Format=disk

[Content]
Bootable=yes
Hostname=demo
KernelCommandLine=console=ttyS0 root=LABEL=root-x86-64 rootfstype=ext4 rw systemd.unit=poweroff.target
UnifiedKernelImages=no
Packages=linux-image-amd64 systemd systemd-sysv systemd-boot systemd-boot-efi
```

`BUILD.bazel`:

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_image", "qemu_ovmf_boot_test")

mkosi_image(
    name = "demo",
    config = "mkosi.conf",
)

qemu_ovmf_boot_test(
    name = "demo_boot_test",
    image = ":demo",
    readiness_marker = "systemd[1]: Hostname set to <demo>.",
)
```

`bazel test :demo_boot_test` builds the image over the network (tracer mode), boots it with OVMF, waits for the hostname line on the serial console, and expects the guest to power off by itself.

## Public API

Load everything from `@rules_mkosi//mkosi:defs.bzl`.
Files under `//mkosi/private` are not API.

| Symbol | Purpose |
| --- | --- |
| `mkosi_image` | Builds a raw disk image. Returns `MkosiImageInfo`. |
| `mkosi_base` | Builds the version-independent part of a release. Returns `MkosiBaseInfo`. |
| `mkosi_config_tree`, `mkosi_source_tree` | Mark a directory as an mkosi configuration tree or `BuildSources` tree. |
| `mkosi_rootfs_payload` | Installs a Bazel file or directory at an absolute image path. |
| `mkosi_reproducibility_manifest` | Normalized JSON projection of a release image for reproducibility comparisons. |
| `qemu_ovmf_boot_test`, `qemu_seabios_boot_test` | Boot an image under QEMU with UEFI or BIOS firmware. |
| `sysupdate_transfers`, `sysupdate_payload` | A/B updates; see [A/B updates](docs/sysupdate-ab.md). |
| `secure_boot_signing_request`, `secure_boot_import_response` | Offline UKI signing; see [Secure Boot](docs/secure-boot.md). |
| `managed_python_test` | Runs a Python test on rules_mkosi's managed interpreter with an empty `PATH`. |
| `MkosiToolchainInfo`, `MkosiQemuToolchainInfo`, `DebianToolsInfo`, `DebianSnapshotInfo` | Toolchain and snapshot providers for advanced integrations. |

Lower-level symbols used by the toolchain repositories and tests (`debian_snapshot`, `qemu_executable`, `qemu_ovmf_toolchain`, `qemu_ovmf_smoke_test`, the `*_boot_config` rules, and `secure_boot_ephemeral_test_fixture`) are exported but are not needed for normal use.

## Building images

`mkosi_image` takes exactly one of:

- `config`: a single mkosi configuration file (tracer mode only).
- `config_tree`: an `mkosi_config_tree` directory containing `mkosi.conf`; `mkosi.conf.d/`, `mkosi.profiles/`, and `mkosi.extra/` keep their relative paths.

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_config_tree", "mkosi_image", "mkosi_rootfs_payload", "mkosi_source_tree")

mkosi_config_tree(name = "os_config", src = "mkosi")

mkosi_source_tree(
    name = "project_sources",
    src = "src",
    executable_paths = ["mkosi.build"],
)

mkosi_rootfs_payload(
    name = "app",
    src = ":app_binary",
    destination = "/usr/local/bin/app",
    executable_paths = [""],  # [""] marks a single-file payload executable.
)

mkosi_image(
    name = "os",
    config_tree = ":os_config",
    source_trees = {"src": ":project_sources"},  # Paths as used by BuildSources=.
    rootfs_payloads = [":app"],
)
```

- Bazel does not preserve source mode bits; list scripts that must stay executable in `executable_paths`.
- `rootfs_payloads` install files as root-owned `0644` (`0755` if executable), directories `0755`, timestamps zero.
  Relative symlinks inside trees are kept.
  Use them for units (`/usr/lib/systemd/system`), sysusers and tmpfiles definitions, binaries, and `/etc/skel` content.
  Do not put secrets in payloads.
- Traversal, colliding or overlapping destinations, duplicate sources, and escaping symlinks fail before anything is staged.

The rule always produces an uncompressed raw disk image; configuration cannot change the output format or location.

## Tracer and release modes

| | `mode = "tracer"` (default) | `mode = "release"` |
| --- | --- | --- |
| Packages | Downloaded over the network, or only from `debian_snapshot` if set; network blocked | Only from `debian_snapshot`; network blocked |
| Caching | Never cached (`no-cache`) | Local, disk, and remote caches |
| Configuration | `config` or `config_tree` | `config_tree` only |
| Required attributes | — (`debian_snapshot` optional) | `debian_snapshot`, `release_seed`, `release_source_date_epoch` |
| `firmware = "bios"`, UKI, dm-verity | Not supported | Supported |

Set `debian_snapshot` on a tracer image to build it without network access, for example in CI.
It then installs packages only from the snapshot, so `Repositories=` may name only components that the snapshot contains.
Like release builds, it then uses fixed sandbox files (`passwd`, `group`, `hosts`, `nsswitch.conf`, and an apt configuration) instead of the host's.

```starlark
mkosi_image(
    name = "release",
    config_tree = ":release_config",
    mode = "release",
    debian_snapshot = "@mkosi_debian_snapshot//:repository",
    release_seed = "00000000-0000-4000-8000-000000000015",
    release_source_date_epoch = 1789200491,
)
```

A release configuration must resolve `Seed=` and `SourceDateEpoch=` to `release_seed` and `release_source_date_epoch`, and `Distribution=`, `Release=`, and `Snapshot=` to the snapshot's values.
It may reference only files inside its declared trees.
Release mode rejects these settings, which could import host state or a network package source:

- `[Match]` and `[TriggerMatch]` sections, `Incremental=`, and proxies;
- `ExtraTrees=` and lifecycle scripts (`mkosi.prepare`, `mkosi.build`, `mkosi.postinst`, and the other `*Scripts=` settings);
- host microcode, host kernel modules, and signing key or certificate settings.

Release images do not keep an APT source; build a new image from a new snapshot to update packages.
Use `rootfs_payloads` instead of scripts for extra content.

A `release_source_date_epoch` of `0` makes systemd-sysusers record a 1970 password change, which forces a password change on first login.
Use a real epoch, such as the snapshot time (`1789200491` for `20260912T080811Z`).

### Legacy BIOS

`firmware = "bios"` is an x86-64 compatibility tier for release images.
It uses GRUB i386-pc, requires one GPT BIOS boot partition of at least 1 MiB and an amd64 snapshot, and rejects UKIs, dm-verity, and Secure Boot.
It has no authenticated or measured boot chain and is not qualified on physical hardware.

### Unsigned UKI and dm-verity

In release mode, `unified_kernel_image = "unsigned"` produces a UKI and `verity = "hash"` (which requires the UKI) produces a dm-verity protected root whose root hash is embedded in the UKI.
Both require UEFI.
Give the `Verity=hash` partition `SizeMinBytes=`, or `Minimize=` together with its data partition; the bundled `systemd-repart` reserves no default size for it, so release builds reject a hash partition without either.
To sign the UKI outside Bazel, see [Secure Boot](docs/secure-boot.md).

### Two-stage releases

`mkosi_base` installs packages from the snapshot once, without an image version.
`mkosi_image(base = ...)` then finalizes it for one version without the snapshot, so a new version does not repeat package installation.
See [two-stage releases](docs/sysupdate-ab.md#two-stage-releases).

### Image identity

`image_id` and `image_version` (or `image_version_file` for versions only known at build time) set mkosi's `ImageId=` and `ImageVersion=` and expand Make variables.
`image_id` uses lowercase letters, digits, `.`, `_`, and `-`; a version uses letters, digits, and `.`.
See [image identity](docs/sysupdate-ab.md#image-identity) for A/B partition labels and their 36-character limit.

## Debian snapshots

`@mkosi_debian_snapshot//:repository` is the built-in snapshot: Debian 13, amd64, `main` only, with a small package set (the Debian tools closure).
For other packages, components, or a different snapshot time, lock your own.

1. Write a JSON specification in the format of [`debian13.spec.json`](mkosi/debian/debian13.spec.json):

   ```json
   {
     "version": 1,
     "sources": [
       {
         "channel": "trixie main non-free-firmware",
         "url": "https://snapshot.debian.org/archive/debian/20260912T080811Z"
       }
     ],
     "archs": ["amd64"],
     "packages": ["amd64-microcode", "openssh-server"]
   }
   ```

   `channel` is the codename followed by its components; `main` is required and `archs` must be `["amd64"]`.

2. Generate the lock (paths are relative to your workspace):

   ```console
   bazel run @rules_mkosi//mkosi/debian:generate_lock -- \
     --spec os/debian.spec.json --output os/debian.lock.json
   ```

   The lock contains the `Pre-Depends`/`Depends` closure of the requested packages plus every `Essential` and `required` package.
   `Recommends` and `Suggests` are not followed.
   Name a provider explicitly when a virtual package is ambiguous.
   Add `--check` in CI to fail when the lock is out of date.

3. Declare it in the root `MODULE.bazel`:

   ```starlark
   debian_tools.snapshot(
       name = "my_os_debian",
       lock = "//os:debian.lock.json",
       # lock_sha256 = "...",  # Optional: also pin the lock's digest.
   )
   use_repo(debian_tools, "my_os_debian")
   ```

   `name` must be unique across all modules and cannot be a built-in `mkosi_debian_*` name; `<name>_packages` is reserved too.

4. Use `@my_os_debian//:repository` as `debian_snapshot`, and select extra components with mkosi's `Repositories=`:

   ```ini
   [Distribution]
   Distribution=debian
   Release=trixie
   Snapshot=20260912T080811Z
   Repositories=non-free-firmware
   ```

The build verifies the snapshot's `InRelease` signature with Debian's archive keyring and every index and package against the lock.
A tampered lock, a missing package, or a `Repositories=` component that is not in the lock fails the build.

## Boot tests

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "qemu_ovmf_boot_test", "qemu_seabios_boot_test")

qemu_ovmf_boot_test(
    name = "uefi_boot_test",
    image = ":demo",
    readiness_marker = "systemd[1]: Hostname set to <demo>.",
)

qemu_seabios_boot_test(
    name = "bios_boot_test",
    image = ":bios_release",  # Requires firmware = "bios".
)
```

The test boots a read-only snapshot of `MkosiImageInfo.raw_image`, waits for the exact `readiness_marker` on the serial console, and requires a clean guest shutdown.

| Attribute | Default | Meaning |
| --- | --- | --- |
| `readiness_marker` | Hostname marker of the test fixtures | Serial line that proves userspace is ready. Set it for your image. |
| `shutdown_markers` | systemd power-off lines | Serial lines that prove a clean shutdown. |
| `machine_args` | `-machine q35 -m 512M` (`pc` for SeaBIOS) | QEMU machine and memory arguments. |
| `accelerator` | `"auto"` | KVM when `/dev/kvm` is readable and writable, otherwise TCG; `"tcg"` forces TCG. |
| `timeout` | `"moderate"` | `short`, `moderate`, or `long`. Deadlines plus 30 s cleanup must fit (60, 300, 900 s). |
| `boot_timeout_seconds`, `qmp_initialization_timeout_seconds`, `shutdown_timeout_seconds`, `diagnostic_bytes` | 180, 15, 30 (60 for SeaBIOS), 65536 | Positive deadlines and retained log size. |

`qemu_ovmf_boot_test` also supports multi-boot scenarios such as A/B updates:

- `allow_reboot = True` keeps one QEMU process, its writable image snapshot, and the UEFI variables across guest reboots;
- `progress_markers` must appear in order before `readiness_marker`;
- `read_only_shares` maps directory targets to virtio-9p mount tags (1 to 31 characters) that the guest mounts with `mount -t 9p -o trans=virtio,ro <tag> <path>`.

Firmware, serial, QEMU, and boot-evidence logs are written to the test's undeclared outputs.
With `--clear-groups`, grant KVM access with a user ACL (`sudo setfacl -m "u:$USER:rw" /dev/kvm`) rather than `kvm` group membership.

## Providers

### `MkosiImageInfo`

Select artifacts by field, never by file name or `DefaultInfo` order.
`DefaultInfo.files` contains every non-`None` artifact.

| Field | Type | Present |
| --- | --- | --- |
| `format_version` | `string` | Always `mkosi-image-v3`. |
| `firmware` | `string` | `uefi` or `bios`. |
| `image_id`, `image_version` | `string` or `None` | When set on the rule. |
| `image_version_file` | `File` or `None` | When set on the rule; contains the version and an optional newline. |
| `raw_image` | `File` | Always. |
| `build_metadata` | `File` | Always. JSON, schema `mkosi-image-build-metadata-v3`: mode, outputs, the snapshot and lock digest when the image is built from `debian_snapshot` or `base`, and for release images the seed and epoch. |
| `partition_metadata` | `File` or `None` | Release images: normalized GPT layout. |
| `uki`, `uki_metadata` | `File` or `None` | `unified_kernel_image = "unsigned"`. |
| `root_image`, `root_hash`, `root_hash_image`, `verity_metadata` | `File` or `None` | `verity = "hash"`. `root_hash` is the lowercase hex root hash. |
| `manifest` | `File` or `None` | `manifest = True`: mkosi's JSON list of the installed packages, including those of a finalized `base`. |
| `image` | `File` | Deprecated alias of `raw_image`. |

### `MkosiBaseInfo`

`mkosi_base` returns `format_version` (`mkosi-base-v1`), `root_tree` (a reproducible tar of the installed root), `initrd` (mkosi's default initrd), and the `debian_snapshot`, `release_seed`, and `release_source_date_epoch` the finalization inherits.

### Other providers

| Provider | Contents |
| --- | --- |
| `MkosiConfigTreeInfo`, `MkosiSourceTreeInfo` | `tree`, `executable_paths`. |
| `MkosiRootfsPayloadInfo` | `artifact`, `destination`, `executable_paths`, `is_tree`. |
| `DebianSnapshotInfo` | Snapshot identity (distribution, release, codename, architecture, components, timestamp, URL), `lock_sha256`, the staged `repository`, and package records. |
| `DebianToolsInfo` | The Debian tools archive, launcher, and provenance. |
| `MkosiToolchainInfo` | mkosi version and provenance, its Python runtime, `python_version`, `resolved_python_version`, `resolved_python_interpreter`. |
| `MkosiQemuToolchainInfo` | QEMU, `qemu-img`, OVMF, and SeaBIOS files with provenance. |
| `QemuBootConfigInfo` | Validated `test_timeout`, deadlines, and `cleanup_margin_seconds` of a `*_boot_config` target. `QemuOvmfBootConfigInfo` is a deprecated alias. |
| `SysupdatePayloadInfo` | See [A/B updates](docs/sysupdate-ab.md#update-payloads). |
| `SecureBootSigningRequestInfo`, `SecureBootSignedUkiInfo` | See [Secure Boot](docs/secure-boot.md). |

## Python

mkosi runs on a Bazel-managed CPython 3.14 resolved through `@rules_python//python:toolchain_type`, independent of your default Python version.
To supply your own interpreter, register a Python 3.14 toolchain whose runtime is an in-build interpreter with its complete files.
Host `interpreter_path` runtimes and other major/minor versions are rejected.

```starlark
register_toolchains("//toolchains:python_3_14")
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `cannot clear supplementary groups` | [Restart the Bazel server without supplementary groups](#run-bazel-without-supplementary-groups). |
| `KERNEL_CAPABILITY_FAILURE` | The host does not meet the [host-kernel contract](docs/design/0004-host-kernel-contract.md). Each `FAIL` line names its remediation. Do not disable the Linux sandbox. |
| `TOOLCHAIN_FAILURE` | A registered toolchain is missing or could not start; check the toolchain setup above. |
| `NETWORK_FAILURE` | A tracer build could not download packages, although apt retries failed downloads. |
| `Failed to connect to https://snapshot.debian.org/...` while fetching a snapshot | The service throttles; Bazel retries 7 times by default. Allow more attempts in your `.bazelrc`, for example `common --http_connector_attempts=12 --http_connector_retry_max_timeout=60s`. |
| `ASSEMBLY_FAILURE` | mkosi failed; its output is preserved in the action log. |
| `VM_FAILURE` | A boot test failed; inspect the retained serial, firmware, and QEMU logs. |
| `release configuration ... is not supported` or `must resolve to ...` | See [release mode](#tracer-and-release-modes). |
| `unable to find library -lc` or `libc of the specified target requires dynamic linking` | See [static bootstrap toolchain](#static-bootstrap-toolchain). |
| Boot tests are slow | QEMU fell back to TCG. The test log prints `QEMU accelerator: tcg`; grant `/dev/kvm` access. |

To qualify a host before building, run the preflight from a rules_mkosi checkout:

```console
bazel shutdown
bazel test --config=kernel_preflight //mkosi/private:kernel_preflight_host_test
```

### Static bootstrap toolchain

The Debian launcher and namespace runner must link fully static, using the first C/C++ toolchain that matches the platform selected by `@rules_mkosi//mkosi/toolchain:bootstrap_platform` (default: the current platform).
If your own toolchain is registered first and cannot link static executables, select a platform that only a static-capable toolchain matches:

```starlark
# BUILD.bazel
platform(
    name = "bootstrap_musl",
    constraint_values = [
        "@platforms//cpu:x86_64",
        "@platforms//os:linux",
        "@zig_sdk//libc:musl",
    ],
)

# MODULE.bazel
register_toolchains("@zig_sdk//libc_aware/toolchain:linux_amd64_musl")
```

```console
# .bazelrc
common --@rules_mkosi//mkosi/toolchain:bootstrap_platform=//:bootstrap_musl
```

The flag affects only the bootstrap executables.
[`e2e/module_resolution/consumer_isolation`](e2e/module_resolution/consumer_isolation) is a working example.

## Further reading

- [A/B updates and two-stage releases](docs/sysupdate-ab.md)
- [Secure Boot and offline signing](docs/secure-boot.md)
- [Behavior catalog](docs/behavior-matrix.md)
- [Design records](docs/design/README.md)
- [Contributing](CONTRIBUTING.md) and [end-to-end tests](e2e/README.md)

## License

Apache-2.0.
mkosi, downloaded as a toolchain, is LGPL-2.1-or-later.
