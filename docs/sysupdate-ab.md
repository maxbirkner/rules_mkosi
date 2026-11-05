# A/B updates with systemd-sysupdate

rules_mkosi builds versioned, immutable UEFI releases that update in place with [`systemd-sysupdate`](https://www.freedesktop.org/software/systemd/man/latest/systemd-sysupdate.html) and fall back to the previous release through [systemd-boot boot counting](https://systemd.io/AUTOMATIC_BOOT_ASSESSMENT/).

| Rule | Role |
| --- | --- |
| `mkosi_image(image_id, image_version)` | A release with one populated root and verity slot and empty inactive slots. |
| `sysupdate_transfers` | Transfer definitions that every release ships in `/usr/lib/sysupdate.d`. |
| `sysupdate_payload` | The update directory that those transfers install from. |
| `mkosi_base` | Optional cached, version-independent base; see [two-stage releases](#two-stage-releases). |

Requirements: `mode = "release"`, `unified_kernel_image = "unsigned"`, `verity = "hash"`, x86-64 UEFI, and systemd 257 or newer in the image (for `PathRelativeTo=explicit`).

## Image identity

`image_id` and `image_version` set mkosi's `ImageId=` and `ImageVersion=`, which appear as `IMAGE_ID` and `IMAGE_VERSION` in `os-release` and the UKI.

- `image_id`: lowercase letters, digits, `.`, `_`, and `-`; shared by every release.
- `image_version`: letters, digits, and `.` only; requires `image_id`.
  `_` separates id and version in artifact names, and `+` and `-` are reserved for boot counting.
- **Label limit:** GPT partition names hold 36 characters, and the longest label is `<image_id>_<image_version>_verity`, so `image_id` and the version together may use at most 28 characters.
  Longer versions fail the build (at analysis for `image_version`, before mkosi starts for `image_version_file`).
  A stamped `<timestamp>.<hash>` version uses this budget quickly; keep `image_id` and the hash short.

Both attributes expand Make variables, so a version can come from a build setting through a `TemplateVariableInfo` target in `toolchains`:

```starlark
load("@bazel_skylib//rules:common_settings.bzl", "string_flag")

string_flag(name = "os_version", build_setting_default = "0")

# A small rule that returns
# platform_common.TemplateVariableInfo({"OS_VERSION": <flag value>}).
os_version_variables(name = "os_version_variables", version = ":os_version")

mkosi_image(
    name = "os",
    config_tree = ":os_config",
    debian_snapshot = "@my_os_debian//:repository",
    image_id = "my-os",
    image_version = "$(OS_VERSION)",
    mode = "release",
    release_seed = "00000000-0000-4000-8000-000000000001",
    release_source_date_epoch = 1755129600,
    rootfs_payloads = [":os_transfers"],
    toolchains = [":os_version_variables"],
    unified_kernel_image = "unsigned",
    verity = "hash",
)
```

### Versions from the build

For a version only known when actions run, such as one derived from the commit, use `image_version_file` instead of `image_version`.
It takes one file containing the version and an optional trailing newline:

```sh
#!/bin/sh
# tools/workspace_status.sh, enabled with
#   build:release --workspace_status_command=tools/workspace_status.sh
echo "STABLE_OS_VERSION $(git log -1 --format=%ct).$(git rev-parse --short=12 HEAD)"
```

```starlark
genrule(
    name = "os_version",
    outs = ["os_version.txt"],
    cmd = "sed -n 's/^STABLE_OS_VERSION //p' bazel-out/stable-status.txt > $@",
    stamp = 1,
)

mkosi_image(
    name = "os",
    image_id = "my-os",
    image_version_file = ":os_version",
    # Other attributes as above, without image_version and toolchains.
)
```

The content is validated like `image_version`; an empty file, for example when the workspace status command is not set, fails with `invalid image_version_file`.
`MkosiImageInfo.image_version` and `SysupdatePayloadInfo.image_version` are then `None`, and their `image_version_file` fields hold the file.

Stable workspace status changes with every commit, so everything depending on the version rebuilds per commit.
Use a two-stage release to avoid repeating package installation.

## Two-stage releases

`mkosi_base` installs packages from the snapshot without any version input, so Bazel caches it across versions.
`mkosi_image(base = ...)` finalizes it for one version: `os-release`, partitions, dm-verity, and the UKI.

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_base", "mkosi_config_tree", "mkosi_image")

mkosi_config_tree(name = "os_base_config", src = "os/base")
mkosi_config_tree(name = "os_image_config", src = "os/image")

mkosi_base(
    name = "os_base",
    config_tree = ":os_base_config",
    debian_snapshot = "@my_os_debian//:repository",
    release_seed = "00000000-0000-4000-8000-000000000001",
    release_source_date_epoch = 1755129600,
    rootfs_payloads = [":os_transfers"],
)

mkosi_image(
    name = "os",
    base = ":os_base",
    config_tree = ":os_image_config",
    image_id = "my-os",
    image_version_file = ":os_version",
    mode = "release",
    unified_kernel_image = "unsigned",
    verity = "hash",
)
```

- `mkosi_base` runs offline like a release image, requires `release_seed` and `release_source_date_epoch`, and its configuration must not set `ImageVersion=`.
- `mkosi_image(base = ...)` inherits the snapshot, `Seed=`, and `SourceDateEpoch=` from the base: do not set `debian_snapshot`, `release_seed`, or `release_source_date_epoch`.
  It requires release mode and UEFI, rejects `source_trees`, and its configuration must not install or remove packages or set `BaseTrees=` or `Initrds=`.
- The result has the same `MkosiImageInfo` as a one-stage release.

Put each setting where it changes:

| Base configuration | Finalize configuration |
| --- | --- |
| `[Distribution]`, including `Snapshot=` and `Repositories=` | `Distribution=` and `Release=`; `Snapshot=` is optional |
| `Seed=`, `SourceDateEpoch=` | the same `Seed=` and `SourceDateEpoch=` |
| `Packages=`, `RemoveFiles=`, `Hostname=`, `mkosi.extra/` | `Bootable=yes`, `Bootloader=`, `UnifiedKernelImages=`, `UnifiedKernelImageFormat=` |
| default initrd: `InitrdPackages=`, `InitrdVolatilePackages=`, `InitrdProfiles=`, `mkosi.initrd.conf` | kernel modules initrd: `KernelModulesInitrd=`, `KernelModulesInitrdInclude=` (`KernelInitrdModules=`), `KernelModulesInitrdExclude=` |
| version-independent `rootfs_payloads` | `KernelCommandLine=`, `mkosi.repart/`, version-dependent `rootfs_payloads` |

Initrd settings in the wrong stage fail the build.
Finalization reruns systemd-sysusers, systemd-tmpfiles, presets, depmod, and `RemoveFiles=`, so repeat `RemoveFiles=` in the finalize configuration for paths these steps recreate.
Files in the base cannot depend on the version, and the default initrd's `initrd-release` carries no image id or version.

## Partition layout

The image needs exactly one populated root partition labelled `<image_id>_<image_version>` and one verity partition labelled `<image_id>_<image_version>_verity`.
Every other root and verity partition is an inactive slot labelled `_empty`, at least as large as the populated slot.
Use fixed sizes, since a slot must hold any later release.
Use repart's `%M` (image id) and `%A` (image version) specifiers in `mkosi.repart/`:

```ini
# 00-esp.conf
[Partition]
Type=esp
Format=vfat
CopyFiles=/boot:/
CopyFiles=/efi:/
SizeMinBytes=512M
SizeMaxBytes=512M

# 10-root.conf
[Partition]
Type=root-x86-64
Label=%M_%A
Format=ext4
CopyFiles=/:/
ExcludeFiles=/boot/
ExcludeFiles=/efi/
SizeMinBytes=2G
SizeMaxBytes=2G
ReadOnly=yes
Verity=data
VerityMatchKey=root
SplitName=root

# 20-root-verity.conf
[Partition]
Type=root-x86-64-verity
Label=%M_%A_verity
SizeMinBytes=128M
SizeMaxBytes=128M
Verity=hash
VerityMatchKey=root
SplitName=root-verity

# 30-root-b.conf
[Partition]
Type=root-x86-64
Label=_empty
SizeMinBytes=2G
SizeMaxBytes=2G
ReadOnly=yes

# 40-root-verity-b.conf
[Partition]
Type=root-x86-64-verity
Label=_empty
SizeMinBytes=128M
SizeMaxBytes=128M
ReadOnly=yes
```

The ESP must hold two UKIs, because the previous release stays bootable.
At boot, the UKI's `roothash=` finds its partitions by UUID, which systemd-repart derives from the root hash, not by slot position or label.

### Compressed read-only roots

A compressed erofs root keeps every slot's fixed size but shrinks what a release ships.
Change only the populated slot's definitions; the inactive `_empty` slots stay as they are:

```ini
# 10-root.conf
[Partition]
Type=root-x86-64
Label=%M_%A
Format=erofs
Compression=zstd
CompressionLevel=3
CopyFiles=/:/
ExcludeFiles=/boot/
ExcludeFiles=/efi/
Minimize=best
SizeMinBytes=2G
SizeMaxBytes=2G
ReadOnly=yes
Verity=data
VerityMatchKey=root
SplitName=root

# 20-root-verity.conf
[Partition]
Type=root-x86-64-verity
Label=%M_%A_verity
Minimize=best
SizeMinBytes=128M
SizeMaxBytes=128M
Verity=hash
VerityMatchKey=root
SplitName=root-verity
```

With `Minimize=best` on both partitions, systemd-repart builds the file system and its hash tree only as large as their contents and writes them to the start of their fixed-size slots.
dm-verity covers only the file system, and the rest of the slot stays zero.
Later releases may grow up to the slot size.
Without `Minimize=best` on the hash partition, dm-verity covers the whole slot, and the payload is as large as the slot.

## mkosi configuration

```ini
[Content]
Bootable=yes
Bootloader=systemd-boot
UnifiedKernelImages=unsigned
UnifiedKernelImageFormat=%i_%v
Packages=
        linux-image-amd64
        systemd
        systemd-boot
        systemd-boot-efi
        systemd-container
        systemd-repart
        systemd-sysv
```

`UnifiedKernelImageFormat=%i_%v` names the UKI `<image_id>_<image_version>.efi`, as the transfers expect.
On Debian 13, `systemd-container` provides `systemd-sysupdate`, `systemd-boot` provides `bootctl` and `systemd-bless-boot`, and `systemd-repart` is needed for runtime partitioning.
The built-in snapshot lacks `systemd-container`, so use a [consumer-owned snapshot](../README.md#debian-snapshots) that also locks the packages of mkosi's default initrd (on Debian 13 including `systemd-cryptsetup` and `libtss2-*`).
[`e2e/smoke/testdata/sysupdate-snapshot/debian.spec.json`](../e2e/smoke/testdata/sysupdate-snapshot/debian.spec.json) is a working minimal set.

## Transfer definitions

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_transfers")

sysupdate_transfers(
    name = "os_transfers",
    image_id = "my-os",
    # boot_attempts = 3,
    # instances = 2,
    # destination = "/usr/lib/sysupdate.d",
)
```

Add the target to `rootfs_payloads` of every release.
It writes three transfers; both partitions are written before the UKI that references them:

| File | Source | Target |
| --- | --- | --- |
| `10-root.transfer` | `<id>_@v.root.@u.raw` | partition of type `root-x86-64` labelled `<id>_@v` |
| `20-root-verity.transfer` | `<id>_@v.root-verity.@u.raw` | partition of type `root-x86-64-verity` labelled `<id>_@v_verity` |
| `90-uki.transfer` | `<id>_@v.efi` | `/EFI/Linux/<id>_@v+@l-@d.efi` on `$BOOT`, or `<id>_@v.efi` with `boot_attempts = 0` |

| Attribute | Default | Meaning |
| --- | --- | --- |
| `boot_attempts` | `3` | `TriesLeft=` of a new UKI. `0` disables boot counting; do not switch a device to `0` while its ESP still holds counted UKIs. |
| `instances` | `2` | Versions kept (`InstancesMax=`); at least 2. |
| `destination` | `/usr/lib/sysupdate.d` | Directory in the image. |

The update directory is chosen at run time with `--transfer-source=`.
Every transfer protects the running version (`ProtectVersion=%A`).

## Update payloads

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_payload")

sysupdate_payload(
    name = "os_payload",
    image = ":os",
    # signed_uki = ":os_signed_uki",
)
```

The output directory contains `<id>_<version>.root.<uuid>.raw`, `<id>_<version>.root-verity.<uuid>.raw`, `<id>_<version>.efi`, and `SHA256SUMS`.
The root and verity files hold only the bytes that dm-verity covers, so a [compressed root](#compressed-read-only-roots) ships at its compressed size rather than its slot size.
The build fails if the image's partition UUIDs do not match its root hash.
`signed_uki` substitutes a UKI from [`secure_boot_import_response`](secure-boot.md) whose signing request names this image's unsigned UKI; signed ESP files such as systemd-boot are rejected.
`SysupdatePayloadInfo` exposes `directory`, `image_id`, and `image_version` or `image_version_file`.

Apply the payload on the device:

```console
/usr/lib/systemd/systemd-sysupdate --transfer-source=/path/to/payload update
systemctl reboot
```

The transfers use `Verify=no`.
Deliver payloads over an authenticated channel, or check `SHA256SUMS` against a trusted digest first.

## Output sizes and caches

Bazel's disk and remote caches store outputs densely, even when they are sparse on disk.

| Output | Size |
| --- | --- |
| `sysupdate_payload` | The root file system, its hash tree, and the UKI. With a compressed root, this is the smallest complete release and suits caches. |
| `MkosiImageInfo` `uki`, `root_hash`, and metadata files | Small. |
| `MkosiImageInfo` `root_image` and `root_hash_image` | One whole slot each, zero after a minimized file system. |
| `MkosiImageInfo` `raw_image` | The whole disk: the ESP and every slot. Only needed to install the first release on a device. |

All outputs of an `mkosi_image` come from one action and are cached together.

## Boot assessment and rollback

systemd-boot boots the newest UKI and decrements its tries counter on each attempt.
`systemd-bless-boot` removes the counter once `boot-complete.target` is reached.
A release whose counter reaches zero is sorted last, so the previous release boots next.
Make health checks prerequisites of `boot-complete.target`:

```ini
[Unit]
Description=Release health check
Before=boot-complete.target
FailureAction=reboot

[Service]
Type=oneshot
ExecStart=/usr/libexec/my-os-health-check

[Install]
RequiredBy=boot-complete.target
```

Enable the unit with a preset file.
With `boot_attempts = 1`, one failed boot falls back to the previous release.
With Secure Boot keys enrolled, a release whose UKI the firmware refuses does not fall back without a reset; see [releases that the firmware refuses](secure-boot.md#releases-that-the-firmware-refuses).
Debian enables `systemd-sysupdate.timer`; disable it unless the transfers name a source the timer can reach.

## Runtime state

The root is read-only, so provide a writable `/var`.
Production images typically let systemd-repart add a `var` partition at first boot with `/usr/lib/repart.d` definitions.
Mirror the image's ESP, root, and verity definitions there first (same `Type=` and fixed sizes) so that `var` is placed after every slot:

```ini
# /usr/lib/repart.d/50-var.conf, after copies of 00-esp.conf to
# 40-root-verity-b.conf that keep only Type= and the size limits.
[Partition]
Type=var
Format=ext4
```

Alternatively, `systemd.volatile=state` on the kernel command line gives a temporary `/var`.

Use a real `release_source_date_epoch`, not `0`; see [release mode](../README.md#tracer-and-release-modes).

## Testing updates

`qemu_ovmf_boot_test` with `allow_reboot`, `progress_markers`, and `read_only_shares` can drive an update inside a VM.
`//e2e/smoke:sysupdate_lifecycle_test` is a complete example: it boots release 1, applies release 2 from a read-only share and checks that it is blessed, then applies release 3, whose health check fails, and checks the fallback to release 2.

These rules have also been used to update and roll back a Debian 13 image on physical x86-64 hardware with `boot_attempts` of 1 and 3.
