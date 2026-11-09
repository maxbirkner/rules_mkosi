# A/B updates with systemd-sysupdate

rules_mkosi builds versioned, immutable UEFI releases that update in place with [`systemd-sysupdate`](https://www.freedesktop.org/software/systemd/man/latest/systemd-sysupdate.html) and fall back to the previous release through [systemd-boot boot counting](https://systemd.io/AUTOMATIC_BOOT_ASSESSMENT/).

| Rule | Role |
| --- | --- |
| `mkosi_image(image_id, image_version)` | A release with one populated root and verity slot and empty inactive slots. |
| `sysupdate_transfers` | Transfer definitions that every release ships in `/usr/lib/sysupdate.d`. |
| `sysupdate_payload` | The update directory that those transfers install from. |
| `sysupdate_signing_request`, `sysupdate_import_signature` | An offline OpenPGP signature of the payload's `SHA256SUMS`, for [updates over HTTP](#updates-over-http). |
| `mkosi_base` | Optional cached, version-independent base; see [two-stage releases](#two-stage-releases). |

Requirements: `mode = "release"`, `unified_kernel_image = "unsigned"`, `verity = "hash"`, x86-64 UEFI, and systemd 257 or newer in the image (for `PathRelativeTo=explicit`).

## Image identity

`image_id` and `image_version` set mkosi's `ImageId=` and `ImageVersion=`, which appear as `IMAGE_ID` and `IMAGE_VERSION` in `os-release` and the UKI.

- `image_id`: lowercase letters, digits, `.`, `_`, and `-`; shared by every release.
- `image_version`: letters, digits, and `.` only; requires `image_id`.
  `_` separates id and version in artifact names, and `+` and `-` are reserved for boot counting.
- **Label limit:** GPT partition names hold 36 characters, and the longest label is `<image_id>_<image_version>_verity`, so `image_id` and the version together may use at most 28 characters.
  Longer versions fail the build (at analysis for `image_version` and `image_version_from_inputs`, before mkosi starts for `image_version_file`).
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

### Versions derived from the inputs

`image_version_from_inputs = True` names a release after its content, so that an unchanged image keeps its version across builds, commits and clean output bases, and devices can skip installing it, while any change to the image gets a new version.

```starlark
mkosi_image(
    name = "os",
    image_id = "my-os",
    image_version_from_inputs = True,
    # Other attributes as above, without image_version, image_version_file and toolchains.
)
```

**What the version covers.**
The version identifies the unsigned build plus the files that you declare; it is fixed, and written into `os-release` and the UKI, before anything is signed.

- Everything that the action building the image reads: the configuration, `rootfs_payloads`, the base or Debian snapshot, and the files of the mkosi, Python and Debian tools toolchains, including the runner and its release patches, together with its command line, environment, and execution requirements.
  The rule hashes the inputs of its own build action, so a new build input, or a ruleset or toolchain update that can change the unsigned image, also changes the version.
- The ruleset scripts of `sysupdate_payload` and `secure_boot_signed_image` and the Debian tools launcher that they run, so that a ruleset update that changes how an image becomes shipped files also changes the version.
- The signing material declared in `version_signing_certificates` and `version_auto_enroll_keys`, and other files listed in `version_inputs`, none of which the build reads.
  `version_signing_certificates` maps each signed binary, by the `esp_path` of its `secure_boot_signing_request` (`""` for the UKI), to the certificate given to that request; `version_auto_enroll_keys` lists the `auto_enroll_keys` of `secure_boot_signed_image`.
  The version covers the files and which binary each certificate signs.
  A sysupdate signing key needs no entry: the `SHA256SUMS` signature is not installed, and a public keyring that the image ships through `rootfs_payloads` is already a build input.

It does not cover the signatures themselves, attributes of the consuming rules such as `secure_boot_enroll` or `compression`, or tools outside the ruleset, such as an external signer; change the image or a declared input when those change.

**One version per signing variant.**
Because the version is fixed before signing, it cannot tell different consumers of one image apart: a development- and a production-signed payload, a signed and an unsigned payload, or a payload signed with either of two certificates would all ship different bytes under the same version.
So every consumer must agree exactly with the image's declaration, and analysis fails otherwise:

- `sysupdate_payload` must sign the UKI with the certificate declared for `""`, or be unsigned when none is declared.
- `secure_boot_signed_image` must sign exactly the declared binaries with their declared certificates, and enroll exactly `version_auto_enroll_keys`.
- A signed binary whose provider lacks `certificate_source`, such as one built by a rule outside rules_mkosi, fails, because its signer is unknown.
- Binaries and keys of a `secure_boot_ephemeral_test_fixture` are exempt, because its throwaway keys change with every build.

The image's own `raw_image` and unsigned UKI cannot be checked; do not ship them from an image that declares signing material.
Build a separate `mkosi_image` for each variant that is signed differently or not at all; its target name and declarations give it its own versions.

```starlark
mkosi_image(
    name = "os",
    image_id = "my-os",
    image_version_from_inputs = True,
    version_signing_certificates = {
        "": ":db_certificate",
        "EFI/systemd/systemd-bootx64.efi": ":db_certificate",
    },
    version_auto_enroll_keys = [":PK.auth", ":KEK.auth", ":db.auth"],
    # Other attributes as above.
)
```

- As when Bazel digests action inputs, files are hashed by content and executable bit with symlinks followed, artifacts declared as symlinks by their target text, and directories are walked.
  Paths are relative to the execution root, without the configuration name in `bazel-out/<config>/bin`, so the version does not depend on the sandbox, the output base, or `--compilation_mode`, but renaming or moving the target changes it.
- The version is the first 16 lowercase hex characters (64 bits) of that SHA-256.
  `MkosiImageInfo.image_version_file` and `SysupdatePayloadInfo.image_version_file` hold it as for `image_version_file`, `MkosiImageInfo.input_digest` holds the full digest, `MkosiImageInfo.version_signing_certificates`, `version_auto_enroll_keys` and `version_inputs` hold the declarations, and the `image_version` output group of `mkosi_image` and `secure_boot_signed_image` contains the version and digest files.
- It requires `image_id` and release mode, and excludes `image_version` and `image_version_file`; the three declaration attributes require it.
  With `verity = "hash"`, `image_id` may have at most 12 characters, to fit the [label limit](#image-identity).
- Unlike a stamped version, the version changes only when the covered files do, so a new commit that does not touch them rebuilds nothing.

**Install by explicit version.**
Content-derived versions do not sort by build order.
systemd-sysupdate selects the newest available version by [version comparison](https://uapi-group.org/specifications/specs/version_format_specification/), and systemd-boot boots the newest entry by default, so with these versions both can pick an older release or skip a newer one.
Name the release to install, try it once, and make it the default only after a healthy boot:

```console
# Install the release, then boot it once; a failed boot returns to the current default.
/usr/lib/systemd/systemd-sysupdate --transfer-source=/path/to/payload update <version>
bootctl set-oneshot my-os_<version>.efi
systemctl reboot
# After the release reached boot-complete.target:
bootctl set-default my-os_<version>.efi
```

Boot entry identifiers omit the [boot counting](#boot-assessment-and-rollback) suffix.
The transfers still protect the running version, and with the default two `instances` the inactive slot is replaced; with more instances, systemd-sysupdate removes the instance that sorts lowest, which need not be the oldest release.

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
[`e2e/smoke/example/debian.spec.json`](../e2e/smoke/example/debian.spec.json) is a working minimal set.

## Transfer definitions

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_transfers")

sysupdate_transfers(
    name = "os_transfers",
    image_id = "my-os",
    # boot_attempts = 3,
    # instances = 2,
    # destination = "/usr/lib/sysupdate.d",
    # url = "https://updates.example.com/my-os",
)
```

Add the target to `rootfs_payloads` of every release.
It writes three transfers; both partitions are written before the UKI that references them:

| File | Source | Target |
| --- | --- | --- |
| `10-root.transfer` | `<id>_@v.root.@u.raw.xz` or `<id>_@v.root.@u.raw` | partition of type `root-x86-64` labelled `<id>_@v` |
| `20-root-verity.transfer` | `<id>_@v.root-verity.@u.raw.xz` or `<id>_@v.root-verity.@u.raw` | partition of type `root-x86-64-verity` labelled `<id>_@v_verity` |
| `90-uki.transfer` | `<id>_@v.efi` | `/EFI/Linux/<id>_@v+@l-@d.efi` on `$BOOT`, or `<id>_@v.efi` with `boot_attempts = 0` |

| Attribute | Default | Meaning |
| --- | --- | --- |
| `boot_attempts` | `3` | `TriesLeft=` of a new UKI. `0` disables boot counting; do not switch a device to `0` while its ESP still holds counted UKIs. |
| `instances` | `2` | Versions kept (`InstancesMax=`); at least 2. |
| `destination` | `/usr/lib/sysupdate.d` | Directory in the image. |
| `url` | `""` | HTTP(S) directory to download signed payloads from; see [updates over HTTP](#updates-over-http). |

Without `url`, the update directory is chosen at run time with `--transfer-source=`.
Every transfer protects the running version (`ProtectVersion=%A`).

## Update payloads

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_payload")

sysupdate_payload(
    name = "os_payload",
    image = ":os",
    # compression = "xz",
    # signed_uki = ":os_signed_uki",
)
```

The output directory contains `<id>_<version>.root.<uuid>.raw`, `<id>_<version>.root-verity.<uuid>.raw`, `<id>_<version>.efi`, and `SHA256SUMS`.
The root and verity files hold only the bytes that dm-verity covers, so a [compressed root](#compressed-read-only-roots) ships at its compressed size rather than its slot size.
`SHA256SUMS` lists the files as shipped.

`compression = "xz"` compresses the root and verity files and appends `.xz` to their names; the UKI stays uncompressed.
systemd-sysupdate 257 decompresses xz, gzip and bzip2 files while it writes them into a slot, from a directory as well as over HTTP; zstd needs systemd 258.
The compressor is single-threaded with fixed settings (`xz -6`, CRC64 check), so the files are deterministic and cacheable, but it compresses only a few MB/s.
It pays off for uncompressed file systems such as ext4; an erofs root that already uses `Compression=` and the hash tree hardly shrink.
The build fails if the image's partition UUIDs do not match its root hash.
`signed_uki` substitutes a UKI from [`secure_boot_import_response`](secure-boot.md) whose signing request names this image's unsigned UKI; signed ESP files such as systemd-boot are rejected.
`SysupdatePayloadInfo` exposes `directory`, `image_id`, and `image_version` or `image_version_file`.

Apply the payload on the device:

```console
/usr/lib/systemd/systemd-sysupdate --transfer-source=/path/to/payload update
systemctl reboot
```

Transfers without `url` use `Verify=no`.
Deliver payloads over an authenticated channel, or check `SHA256SUMS` against a trusted digest first.

## Updates over HTTP

With `url`, the transfers download releases from a web server or object storage instead of a local directory, and verify them:

```starlark
sysupdate_transfers(
    name = "os_transfers",
    image_id = "my-os",
    url = "https://updates.example.com/my-os",
)
```

systemd-sysupdate downloads `<url>/SHA256SUMS` and `<url>/SHA256SUMS.gpg`, checks the signature (`Verify=yes`), selects the newest version that `SHA256SUMS` lists, and downloads its files, checking each against its digest.
Publish one payload directory and its `SHA256SUMS.gpg` at the URL; devices on any older release update to it.
systemd expands specifiers in the URL, such as `%A` for the running `IMAGE_VERSION`; write `%%` for a literal `%`.
The device needs network access and the `gpg` package, which `systemd-pull` runs to check the signature.

### Signing SHA256SUMS offline

As with [Secure Boot](secure-boot.md), rules_mkosi never handles the signing key: Bazel creates a request, a signer outside Bazel signs, and Bazel verifies the result.

```starlark
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_import_signature", "sysupdate_signing_request")

sysupdate_signing_request(
    name = "os_payload_signing_request",
    payload = ":os_payload",
    public_key = "keys/updates.pgp",  # The signer's OpenPGP certificate, binary or ASCII-armored.
)

sysupdate_import_signature(
    name = "os_payload_signed",
    request = ":os_payload_signing_request",
    signature = "signed/SHA256SUMS.gpg",  # Returned by the external signer.
)
```

1. `sysupdate_signing_request` outputs the payload's `SHA256SUMS`, the certificate in binary form as `signer.pgp`, and `request.json` (`mkosi-sysupdate-signing-request-v1`).
   The request binds the SHA-256 of `SHA256SUMS`, the files and digests that it lists, and the signer's fingerprint.
   A secret key, several certificates, or a payload that is already signed fail the build.
   It returns `SysupdateSigningRequestInfo`.
2. The external signer checks the request and makes a detached OpenPGP signature of exactly that `SHA256SUMS`, for example with `gpg --local-user <fingerprint> --output SHA256SUMS.gpg --detach-sign SHA256SUMS`.
3. `sysupdate_import_signature` accepts the signature only if it is exactly one detached signature and `sqv` from the Debian tools verifies it over the requested `SHA256SUMS` with the requested certificate, and stores it in binary form.
   Several signatures are rejected, because `gpg` on the device fails if it lacks the key of any of them.
   It returns the payload's `SysupdatePayloadInfo` with `signature` set, and the payload directory and `SHA256SUMS.gpg` as its files.

Publish both side by side, for example:

```console
bazel build //:os_payload_signed
cp bazel-bin/os_payload/* bazel-bin/os_payload_signed/SHA256SUMS.gpg /srv/updates/my-os/
```

The payload stays deterministic and cacheable; only the signature depends on the signer.
Use `compression = "xz"` on the payload to download less.

### Shipping the public key

`systemd-pull` (systemd 257) checks the signature against `/etc/systemd/import-pubring.gpg`, or `/usr/lib/systemd/import-pubring.gpg` if that does not exist.
Debian's `systemd-container` ships the latter with distribution keys, so ship your signer's certificate as the former, which then is the only trusted keyring:

```starlark
mkosi_rootfs_payload(
    name = "update_keyring",
    src = "keys/updates.pgp",
    destination = "/etc/systemd/import-pubring.gpg",
)
```

Add it to `rootfs_payloads` of the base or release.
`gpg` reads the file as a keyring, which must be binary: export the certificate with `gpg --export <fingerprint>`, or use the request's `signer.pgp`.
To rotate keys, concatenate the old and the new certificate in the keyring of one release before you sign with the new key.

| Protected against | Not protected against |
| --- | --- |
| The signing key reaching any Bazel action, cache, remote executor, runfiles tree, log, or CI artifact. | A compromised external signer. |
| A substituted `SHA256SUMS`, payload file, signature, or key, including a signature of another payload by the trusted key. | Withheld releases: signatures do not expire, so a server can keep offering an old signed release, though devices never install one older than they run. |

### Testing HTTP updates

`sysupdate_ephemeral_test_fixture(payloads = [...])` signs the `SHA256SUMS` of payloads with a throwaway key that never leaves one uncached action that runs on the local machine, never remotely; never use it for production.
Use it as the `public_key` of requests and the `signature` of imports; each import selects the fixture's signature that verifies.
Its output group `keyring` holds a directory with the certificate as `import-pubring.gpg`.

`qemu_ovmf_boot_test(http_shares = {":os_payload_signed": "updates"})` serves the files of the target, and the contents of its directories, at `http://10.0.2.100/updates/` through a virtio network interface on QEMU's user network, which reaches nothing else; give the guest the address `10.0.2.15/24`.

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

`qemu_ovmf_boot_test` with `allow_reboot`, `progress_markers`, and `read_only_shares` or `http_shares` can drive an update inside a VM.
`//e2e/smoke:sysupdate_lifecycle_test` is a complete example: it boots release 1, downloads release 2 over HTTP with a signed `SHA256SUMS` and checks that it is blessed, then installs release 3 from compressed files, whose health check fails, and checks the fallback to release 2.
The test's key cannot be part of the images, which the payloads it signs depend on, so the guest bind-mounts the fixture's keyring from a read-only share over `/usr/lib/systemd/import-pubring.gpg`.

These rules have also been used to update and roll back a Debian 13 image on physical x86-64 hardware with `boot_attempts` of 1 and 3.
