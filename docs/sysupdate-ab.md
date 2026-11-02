# A/B updates with systemd-sysupdate

rules_mkosi builds versioned, immutable UEFI releases that update themselves
in place with
[`systemd-sysupdate`](https://www.freedesktop.org/software/systemd/man/latest/systemd-sysupdate.html)
and fall back to the previous release through
[systemd-boot boot counting](https://systemd.io/AUTOMATIC_BOOT_ASSESSMENT/).
The rules produce three things:

- `mkosi_image(image_id, image_version)` builds a release whose root and
  dm-verity partitions occupy one slot and whose other slots are empty.
- `sysupdate_transfers` generates the transfer definitions that every release
  ships in `/usr/lib/sysupdate.d`.
- `sysupdate_payload` projects a release into the files those transfers
  install on a running system.

The rules require `mode = "release"`, `unified_kernel_image = "unsigned"`, and
`verity = "hash"`, and target x86-64 UEFI. They require systemd 257 or newer
in the image, because the transfers use `PathRelativeTo=explicit`.

## Image identity

`image_id` and `image_version` become mkosi's `ImageId=` and `ImageVersion=`,
and therefore `IMAGE_ID` and `IMAGE_VERSION` in `os-release` and in the UKI.
They are exposed as `MkosiImageInfo.image_id`/`image_version` and in the
`image` object of the build metadata.

- `image_id` uses lowercase letters, digits, `.`, `_`, and `-`. It is shared by
  every release of the image.
- `image_version` uses only letters, digits, and `.`, and requires `image_id`.
  systemd-sysupdate accepts only letters, digits, and `.,_-+` in a version;
  `_` separates the id from the version in every artifact name, and `+` and `-`
  introduce the boot-counting suffix of a UKI, so none of them may appear in a
  version.

Both attributes expand Make variables, so the version can come from a build
setting rather than being edited in `BUILD` files:

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

## Partition layout

A versioned dm-verity image must contain exactly one populated root partition
labelled `<image_id>_<image_version>` and one populated verity partition
labelled `<image_id>_<image_version>_verity`. Every other root and verity
partition is an inactive slot labelled `_empty`, the label systemd-sysupdate
looks for when it chooses where to install. Inactive slots must be at least as
large as the populated slot, and all sizes must be fixed, because a slot has to
hold any later release. The partition metadata projection enforces these rules
and records each partition's UUID.

Use repart's `%M` (image id) and `%A` (image version) specifiers in the image's
`mkosi.repart/` definitions:

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

The ESP must hold two UKIs at once, because the previous release stays
bootable. Excluding `/boot/` and `/efi/` from the root keeps the UKI out of the
root partition while preserving the mount points.

systemd-repart derives the UUIDs of a verity data and hash partition from the
root hash: the first and last 128 bits respectively. The UKI's `roothash=`
therefore finds the matching partitions at boot through these UUIDs, not
through slot positions or labels.

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

`UnifiedKernelImageFormat=%i_%v` names the installed UKI
`<image_id>_<image_version>.efi`, which is the name the UKI transfer matches.
On Debian 13 the guest needs `systemd-container` for
`/usr/lib/systemd/systemd-sysupdate`, `systemd-boot` for `bootctl` and
`systemd-bless-boot`, and `systemd-repart` for runtime partitioning. The
built-in snapshot does not lock `systemd-container`, so use a
[consumer-owned snapshot](../README.md#consumer-owned-debian-snapshots). Its
specification must also list the packages of mkosi's default initrd, which on
Debian 13 includes `systemd-cryptsetup` and the `libtss2-*` libraries; the
end-to-end fixture
[`debian.spec.json`](../e2e/smoke/testdata/sysupdate-snapshot/debian.spec.json)
is a working minimal set.

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

The target is a typed rootfs payload; add it to `rootfs_payloads` of every
release. It writes three transfers, ordered so that both partitions are
written before the UKI that references them:

| File | Source | Target |
| --- | --- | --- |
| `10-root.transfer` | `<id>_@v.root.@u.raw` | partition of type `root-x86-64` labelled `<id>_@v` |
| `20-root-verity.transfer` | `<id>_@v.root-verity.@u.raw` | partition of type `root-x86-64-verity` labelled `<id>_@v_verity` |
| `90-uki.transfer` | `<id>_@v.efi` | `/EFI/Linux/<id>_@v+@l-@d.efi` on `$BOOT`, or `<id>_@v.efi` with `boot_attempts = 0` |

Sources use `Path=/` with `PathRelativeTo=explicit`, so the update directory is
chosen at run time with `--transfer-source=`. `@u` in a source name sets the
target partition's UUID to the root-hash-derived UUID, which is what lets the
new UKI find its root. Every transfer has `ProtectVersion=%A`, so the running
release is never overwritten, and keeps at most `instances` versions. New UKIs
are installed with `TriesLeft=<boot_attempts>`.

systemd-sysupdate names a new UKI after the first target `MatchPattern=` and
defaults to `TriesLeft=3`, so `boot_attempts = 0` disables boot counting by
listing `<id>_@v.efi` first, ahead of the counted patterns. The counter-free
pattern then also matches counted names, so do not switch a device to
`boot_attempts = 0` while its ESP still holds boot-counted UKIs.

## Update payloads

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_payload")

sysupdate_payload(
    name = "os_payload",
    image = ":os",
    # signed_uki = ":os_signed_uki",
)
```

The output directory contains `<id>_<version>.root.<uuid>.raw`,
`<id>_<version>.root-verity.<uuid>.raw`, `<id>_<version>.efi`, and a
`SHA256SUMS` manifest; zero runs stay sparse. The action fails, leaving no
output, when the image's GPT UUIDs differ from the UUIDs derived from its root
hash. `signed_uki` substitutes a UKI imported with
[`secure_boot_import_response`](secure-boot.md); the action also fails unless
that UKI's signing request names the SHA-256 of this image's unsigned UKI.
`SysupdatePayloadInfo` exposes the directory, image id, and version.

Apply the payload on the device:

```console
/usr/lib/systemd/systemd-sysupdate --transfer-source=/path/to/payload update
systemctl reboot
```

The transfers use `Verify=no`: the payload is trusted as delivered. Deliver it
over an authenticated channel, or check `SHA256SUMS` against a trusted digest
first.

## Boot assessment and rollback

systemd-boot boots the newest UKI and decrements its tries counter on every
attempt. `systemd-bless-boot` removes the counter once `boot-complete.target`
is reached; a release whose counter reaches zero is sorted after every other
entry, so the next boot selects the previous release. Make health checks
prerequisites of `boot-complete.target`, and reboot when they fail:

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

Enable the unit, for example with a preset file, since mkosi applies presets.
With `boot_attempts = 1`, a single failed boot falls back to the previous
release. Debian also enables `systemd-sysupdate.timer`; disable it unless the
transfers name a source that the timer can reach.

## Runtime state

The root is read-only, so give the system a writable `/var`. Production images
typically let systemd-repart add a `var` partition that grows into the rest of
the disk, using runtime `/usr/lib/repart.d` definitions. Mirror the image's
ESP, root, and verity definitions there first, with the same `Type=` and fixed
sizes, so that systemd-repart matches every existing slot in order before it
places `var` after them:

```ini
# /usr/lib/repart.d/50-var.conf, after copies of 00-esp.conf to
# 40-root-verity-b.conf that keep only Type= and the size limits.
[Partition]
Type=var
Format=ext4
```

The end-to-end test instead uses `systemd.volatile=state` on the kernel
command line for a temporary `/var`.

## Release epoch

`release_source_date_epoch = 0` also sets every account's last password change
to 1970 when systemd-sysusers creates `/etc/shadow`, so a login is forced to
change the password immediately. Use a real epoch, such as the time of the
Debian snapshot (`1755129600` for `20250814T000000Z`), and set the matching
`SourceDateEpoch=` and `SOURCE_DATE_EPOCH` in the configuration.

## Verification

`//e2e/smoke:sysupdate_lifecycle_test` builds releases 1, 2, and 3 of one
image with `boot_attempts = 1`. It boots release 1 with QEMU and OVMF, applies
release 2 from a read-only virtio-9p share, reboots, and checks that release 2
runs from its own verity root and is blessed. It then applies release 3, whose
health check always fails, and checks that systemd-boot falls back to release
2. The test uses `qemu_ovmf_boot_test` with `allow_reboot`, ordered
`progress_markers`, and `read_only_shares`, which consumers can use for their
own update tests.

The same rules have also been used to build a Debian 13 image that was updated
in place and rolled back on physical x86-64 hardware, with `boot_attempts` of
both 1 and 3.
