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
| Host | Linux x86-64. With local execution, the host is the execution platform, and rules_mkosi's default bootstrap execution platform always declares Linux x86-64, so on another host the `llvm` module's Linux x86-64 compiler fails when it runs. |
| Execution platform | Linux x86-64, kernel 5.12 or newer, unprivileged user and mount namespaces under Bazel's Linux sandbox (see [host-kernel contract](docs/design/0004-host-kernel-contract.md)). |
| Bazel server | Any unprivileged user; neither sudo nor a server without supplementary groups is needed (see [supplementary groups](#supplementary-groups)). |
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

rules_mkosi is not yet published to the Bazel Central Registry; use an override.
Add to the root `MODULE.bazel`:

```starlark
bazel_dep(name = "rules_mkosi", version = "0.0.0")
local_path_override(module_name = "rules_mkosi", path = "/path/to/rules_mkosi")

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
Registering them downloads nothing: mkosi, QEMU, the firmware, and the Debian userspace are fetched only when a target uses one of these toolchains.
Its statically linked [bootstrap executables](#static-bootstrap-toolchain) use the musl C/C++ toolchain of the [`llvm` module](https://registry.bazel.build/modules/llvm) without any registration or module extension setup: your own C/C++ targets keep using your toolchains, and the LLVM toolchain and the musl and libc++ sources are downloaded only when a bootstrap executable is built.
Only [your own bootstrap or execution platforms](#static-bootstrap-toolchain) that name its constraints need a `bazel_dep` on `llvm`.
If you use the `llvm` module yourself, the bootstrap executables share its version, its `llvm.version(...)` choice, and your overrides of it.
Unsupported or conflicting mkosi versions fail during module resolution, and only the root module may set the toolchain `name`.

### Supplementary groups

Image builds run from a normally started Bazel server, including one whose user has supplementary groups such as `docker` or `adm`.
Bazel's Linux sandbox denies `setgroups`, so no action can drop these groups, and rules_mkosi's user namespaces keep them as unmapped IDs (the overflow GID, usually `nogroup`).
Unmapped groups cannot own files or be assigned to them, so they do not change image contents, and release builds stay offline and reproducible.
The Debian tools namespace detaches the host root, so there the groups only apply to the action's mounted inputs and outputs, which the Bazel server reads with the same groups.
Like any other Bazel action, the image action itself can read host files that the groups make readable.
For stricter isolation, start the server without supplementary groups, for example through `sudo setpriv --reuid="$(id -u)" --regid="$(id -g)" --clear-groups`.

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
For a complete release configuration, with a locked Debian snapshot, UKI, dm-verity, A/B updates, and a boot test, see the [release example](e2e/smoke/example/README.md).

## Public API

Load everything from `@rules_mkosi//mkosi:defs.bzl`.
Files under `//mkosi/private` are not API.
The [API reference](docs/api/defs.md), generated with Stardoc, documents every attribute and provider field; the module extensions are documented in [`mkosi`](docs/api/mkosi_extension.md) and [`debian_tools`](docs/api/debian_tools_extension.md).

| Symbol | Purpose |
| --- | --- |
| `mkosi_image` | Builds a raw disk image. Returns `MkosiImageInfo`. |
| `mkosi_base` | Builds the version-independent part of a release. Returns `MkosiBaseInfo`. |
| `mkosi_config_tree`, `mkosi_source_tree` | Declare or assemble an mkosi configuration tree; mark a `BuildSources` tree. |
| `mkosi_rootfs_payload` | Installs a Bazel file or directory at an absolute image path. |
| `mkosi_reproducibility_manifest` | Normalized JSON projection of a release image for reproducibility comparisons. |
| `qemu_ovmf_boot_test`, `qemu_seabios_boot_test` | Boot an image under QEMU with UEFI (optionally [Secure Boot](docs/secure-boot.md#testing-enrollment-in-qemu)) or BIOS firmware. |
| `sysupdate_transfers`, `sysupdate_payload` | A/B updates; see [A/B updates](docs/sysupdate-ab.md). |
| `sysupdate_signing_request`, `sysupdate_import_signature` | Offline OpenPGP signing of update payloads for HTTP updates; see [signed payloads](docs/sysupdate-ab.md#updates-over-http). |
| `secure_boot_signing_request`, `secure_boot_import_response` | Offline signing of UKIs and ESP boot binaries such as systemd-boot; see [Secure Boot](docs/secure-boot.md). |
| `secure_boot_signing_manifest` | Lists signing requests for an external signer such as the reference `@rules_mkosi//mkosi:secure_boot_signer`; see [signing in CI](docs/secure-boot.md#signing-in-ci). |
| `secure_boot_signed_image` | Disk image with signed boot binaries and Secure Boot key auto-enrollment; see [Secure Boot](docs/secure-boot.md#signed-disk-images-and-key-auto-enrollment). |
| `managed_python_test` | Runs a Python test on rules_mkosi's managed interpreter with an empty `PATH`. |
| `MkosiToolchainInfo`, `MkosiQemuToolchainInfo`, `DebianToolsInfo`, `DebianSnapshotInfo` | Toolchain and snapshot providers for advanced integrations. |

Lower-level symbols used by the toolchain repositories and tests (`debian_snapshot`, `qemu_executable`, `qemu_ovmf_toolchain`, `qemu_ovmf_smoke_test`, the `*_boot_config` rules, `secure_boot_ephemeral_test_fixture`, and `sysupdate_ephemeral_test_fixture`) are exported but are not needed for normal use.

`@rules_mkosi//mkosi/tools:esp_manifest` checks a disk image before install tooling writes it to a device: it prints the ESP manifest of a `secure_boot_signed_image`, or lists and extracts other ESP files, without mounting the image; see [reading the ESP manifest](docs/secure-boot.md#reading-the-esp-manifest-of-a-disk-image).

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
- `mkosi_config_tree` can also assemble a tree, see [Assembling configuration trees](#assembling-configuration-trees).
- `rootfs_payloads` install files as root-owned `0644` (`0755` if executable), directories `0755`, timestamps zero.
  Relative symlinks inside trees are kept.
  Use them for units (`/usr/lib/systemd/system`), sysusers and tmpfiles definitions, binaries, and `/etc/skel` content.
  Do not put secrets in payloads.
- Traversal, colliding or overlapping destinations, duplicate sources, and escaping symlinks fail before anything is staged.

The rule always produces an uncompressed raw disk image; configuration cannot change the output format or location.

### Assembling configuration trees

Instead of `src`, `mkosi_config_tree` can assemble a tree from `srcs`, placed at their path relative to the package of the listed target minus `strip_prefix`, and from `trees`, keyed by the directory to place them in.
A `trees` target may be listed under several keys, for example to share files between the image and mkosi's default initrd, which reads `mkosi.initrd.conf/`.
An `mkosi_config_tree` or a generated directory in `trees` contributes its contents, and the former also its `executable_paths`; other targets contribute their files at their package-relative paths.

```starlark
mkosi_config_tree(
    name = "boot_splash",
    srcs = glob(["splash/**"]),
    strip_prefix = "splash",
    executable_paths = ["usr/lib/systemd/system-generators/splash-generator"],
)

mkosi_config_tree(
    name = "os_config",
    srcs = glob(["mkosi/**"]),  # mkosi/mkosi.conf becomes mkosi.conf.
    strip_prefix = "mkosi",
    trees = {
        "mkosi.extra": ":boot_splash",
        "mkosi.initrd.conf/mkosi.extra": ":boot_splash",
    },
    executable_paths = ["mkosi.extra/usr/local/bin/tool"],
)
```

One action copies the inputs into a new directory; directories merge, while duplicate files fail.
Traversal, absolute paths, and collisions fail during analysis where the paths are known.
Bazel copies what a symlink points to, so the action rejects `srcs` and `trees` source files that are, or lie below, a symlink in their package, such as the links of `systemctl enable`.
Wrap a directory with symlinks in `mkosi_config_tree(src = ...)` and map it through `trees`; `src` keeps relative links and rejects absolute or escaping ones.
The check sees symlinks only when the action runs locally or sandboxed: under remote execution, or on a remote-cache hit for an action first run there, Bazel may deliver a symlinked source as the content that it points to.
Inside a fetched archive repository, a committed link that mimics Bazel's own layout may still be followed, as the archive can ship arbitrary content anyway.

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
It has no authenticated or measured boot chain.
Like the UEFI tier, it is qualified on physical hardware only as far as a release's [hardware qualification](docs/hardware-qualification.md) records it.

### Unsigned UKI and dm-verity

In release mode, `unified_kernel_image = "unsigned"` produces a UKI and `verity = "hash"` (which requires the UKI) produces a dm-verity protected root whose root hash is embedded in the UKI.
Both require UEFI.
Give the `Verity=hash` partition `SizeMinBytes=`, or `Minimize=` together with its data partition; the bundled `systemd-repart` reserves no default size for it, so release builds reject a hash partition without either.
To sign the UKI outside Bazel, see [Secure Boot](docs/secure-boot.md).

### Compressed read-only roots

A dm-verity root is read-only, so it can be a compressed [erofs](https://erofs.docs.kernel.org/) file system instead of ext4, which shrinks the root to a fraction of its uncompressed size.
Set `Format=erofs` and `Compression=zstd` or `lzma`, optionally with `CompressionLevel=`, on the `Verity=data` partition, and `Minimize=best` on it and on its `Verity=hash` partition, so that the file system and the hash tree only cover the root's contents.
`lzma` gives the smallest root but decompresses slowest at run time; `zstd` reads faster for a slightly larger root.
Higher levels mostly cost build time: for the 274 MB root of the A/B test image, zstd level 3 gives 175 MiB in 2 s, level 15 170 MiB in 42 s, and lzma level 6 167 MiB in 12 s.
Already compressed files, such as Debian's xz-compressed kernel modules, gain nothing.
mkosi's default initrd loads the `erofs` and `dm-verity` modules; if you set `KernelInitrdModules=`, keep `default` or list both.
For A/B slots, update payloads and which outputs suit Bazel caches, see [compressed A/B roots](docs/sysupdate-ab.md#compressed-read-only-roots).

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

2. Declare the lock targets next to the specification in `os/BUILD.bazel`:

   ```starlark
   load("@rules_mkosi//mkosi:defs.bzl", "debian_lock")

   debian_lock(
       name = "debian_lock",
       spec = "debian.spec.json",
       lock = "debian.lock.json",
   )
   ```

   Then generate or refresh the lock with one command (it needs network access; extra arguments such as `--release` reach the generator):

   ```console
   bazel run //os:debian_lock.update
   ```

   The lock contains the `Pre-Depends`/`Depends` closure of the requested packages plus every `Essential` and `required` package.
   `Recommends` and `Suggests` are not followed.
   Name a provider explicitly when a virtual package is ambiguous.

   The lock records `spec_sha256`, the SHA-256 of the normalized specification.
   `//os:debian_lock_test` fails without network access when the lock does not match its specification and names the update command, so humans and bots such as Renovate refresh the lock with that single command after editing the specification.
   Locks generated before `spec_sha256` existed stay valid for builds but fail this test until they are regenerated once.
   Without the macro, run `bazel run @rules_mkosi//mkosi/debian:generate_lock -- --spec os/debian.spec.json --output os/debian.lock.json`; add `--check-spec` to only check it offline, or `--check` to regenerate it and compare.

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

Further attributes set the shutdown markers, QEMU machine arguments, the accelerator (KVM with a TCG fallback by default), the deadlines, and the retained log size; see [`qemu_ovmf_boot_config`](docs/api/defs.md#qemu_ovmf_boot_config) and [`qemu_seabios_boot_config`](docs/api/defs.md#qemu_seabios_boot_config).

`qemu_ovmf_boot_test` also supports multi-boot scenarios such as A/B updates:

- `allow_reboot = True` keeps one QEMU process, its writable image snapshot, and the UEFI variables across guest reboots;
- `progress_markers` must appear in order before `readiness_marker`;
- `read_only_shares` maps directory targets to virtio-9p mount tags (1 to 31 characters) that the guest mounts with `mount -t 9p -o trans=virtio,ro <tag> <path>`;
- `http_shares` maps targets to URL paths: the guest downloads their files, and the contents of their directories, from `http://10.0.2.100/<path>/` through a virtio network interface on QEMU's user network, which reaches nothing else.
  Give the guest the address `10.0.2.15/24`, statically or with DHCP.

Firmware, serial, QEMU, and boot-evidence logs are written to the test's undeclared outputs.
Membership in the `kvm` group grants KVM access.
A Bazel server started without supplementary groups needs a user ACL instead, such as `sudo setfacl -m "u:$USER:rw" /dev/kvm`.

## Providers

Select artifacts through provider fields, never by file name or `DefaultInfo` order; `DefaultInfo.files` of `mkosi_image` contains every artifact that is not `None`.
Without a custom rule, `filegroup(srcs = [":os"], output_group = "raw_image")` or `bazel build --output_groups=raw_image` selects only the raw disk image of `mkosi_image` or `secure_boot_signed_image`.
[`MkosiImageInfo`](docs/api/defs.md#MkosiImageInfo) has the raw image, build and partition metadata, and the UKI and dm-verity artifacts of release images, and [`MkosiBaseInfo`](docs/api/defs.md#MkosiBaseInfo) the output of `mkosi_base`.
The [API reference](docs/api/defs.md) lists the fields of every provider; for the update and signing providers see also [A/B updates](docs/sysupdate-ab.md#update-payloads) and [Secure Boot](docs/secure-boot.md).
`QemuOvmfBootConfigInfo` is a deprecated alias of `QemuBootConfigInfo`.

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

The Debian launcher and namespace runner must link fully static.
They are built for the platform selected by `@rules_mkosi//mkosi/toolchain:bootstrap_platform`; by default, that is a Linux x86-64 platform with the `llvm` module's `@llvm//constraints/libc:musl` and `@llvm//constraints/pie:off` constraints, while their runfiles keep the current platform.
Their transition puts `@rules_mkosi//mkosi/toolchain/bootstrap_cc:all`, the `llvm` module's Linux x86-64 C/C++ toolchain, before every registered C/C++ toolchain with `--extra_toolchains`, so neither your registrations nor the order of your dependencies change it, and no registration is needed.
It matches only Linux x86-64 platforms with `@llvm//constraints/libc:musl`, and only below the bootstrap executables.
The transition also puts the platform selected by `@rules_mkosi//mkosi/toolchain:bootstrap_execution_platform` (default: the same static platform, `@rules_mkosi//mkosi/toolchain/bootstrap_cc:linux_x86_64_musl`) first in `--extra_execution_platforms`, so that the toolchain's own helper tools, which are built for the execution platform, link statically against musl too, without a host C/C++ compiler or the `llvm` module's glibc runtime.
The first build compiles musl, libc++, and the compiler runtimes from source, once for the executables and once, optimized, for the helper tools.

The compile and link actions below the bootstrap executables run on that execution platform.
The default declares no `exec_properties`, so with remote execution they get only `--remote_default_exec_properties`.
To keep the `exec_properties` of your own execution platform, select a Linux x86-64 child of it with the musl and non-PIE constraints:

```starlark
# BUILD.bazel
platform(
    name = "rbe_bootstrap",
    parents = ["//:rbe"],
    constraint_values = [
        "@llvm//constraints/libc:musl",
        "@llvm//constraints/pie:off",
    ],
)
```

```console
# .bazelrc
common --@rules_mkosi//mkosi/toolchain:bootstrap_execution_platform=//:rbe_bootstrap
```

To select another bootstrap platform, give it the musl constraint, and `@llvm//constraints/pie:off` for executables without a dynamic section, which older `llvm` module versions otherwise link as static PIE; `parents = ["@rules_mkosi//mkosi/toolchain/bootstrap_cc:linux_x86_64_musl"]` inherits both:

```console
# .bazelrc
common --@rules_mkosi//mkosi/toolchain:bootstrap_platform=//platforms:my_static_platform
```

Naming the `@llvm//constraints/...` labels in your own platforms, as in the remote-execution example, requires your own `bazel_dep(name = "llvm", version = "0.8.5")` or newer, since a module can only use the repositories of its direct dependencies; inheriting them through `parents` does not.
The flags affect only the bootstrap executables.
For a bootstrap platform without the musl constraint, the first registered C/C++ toolchain that matches it builds the executables and must link them statically.
[`e2e/module_resolution/consumer_isolation`](e2e/module_resolution/consumer_isolation), with a first-priority glibc toolchain of another compiler and its own musl bootstrap platform, [`e2e/module_resolution/rules_cc_first`](e2e/module_resolution/rules_cc_first), with rules_cc's host toolchain ahead of rules_mkosi's registrations, and [`e2e/module_resolution/llvm_consumer`](e2e/module_resolution/llvm_consumer), which pins the `llvm` module and registers its toolchains for its own glibc targets, are working examples.
[`e2e/module_resolution`](e2e/module_resolution/README.md) describes what each module-resolution fixture checks.

## Further reading

- [Release example](e2e/smoke/example/README.md)
- [A/B updates and two-stage releases](docs/sysupdate-ab.md)
- [Secure Boot and offline signing](docs/secure-boot.md)
- [Behavior catalog](docs/behavior-matrix.md)
- [Physical hardware qualification](docs/hardware-qualification.md)
- [Design records](docs/design/README.md)
- [Contributing](CONTRIBUTING.md) and [end-to-end tests](e2e/README.md)

## License

Apache-2.0.
mkosi, downloaded as a toolchain, is LGPL-2.1-or-later.
