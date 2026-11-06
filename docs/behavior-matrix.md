# Public behavior coverage

Each maintained public behavior has a stable ID below.
[`mkosi/tests/behavior_matrix.tsv`](../mkosi/tests/behavior_matrix.tsv) maps every ID to its tests, and `//mkosi/tests:behavior_matrix_test` fails on missing, duplicate, malformed, or unmapped IDs.

| Layer | Meaning |
| --- | --- |
| `analysis`, `artifact` | Root-module tests of the ruleset. |
| `consumer` | The independent `e2e/smoke` module. |
| `runtime` | An executed launcher, image build, or VM boot. |
| `module-resolution` | A nested-module fixture under `e2e/module_resolution`. |

## Rules and attributes

<!-- behavior:BHV-IMAGE-MODE -->
`mkosi_image.mode` defaults to uncached `tracer`, accepts offline, cacheable `release`, and rejects other values.

<!-- behavior:BHV-IMAGE-FIRMWARE -->
`mkosi_image.firmware` defaults to `uefi`.
`bios` is release-only, requires an amd64 snapshot, uses GRUB i386-pc, and rejects UKI and Secure Boot settings.

<!-- behavior:BHV-IMAGE-CONFIG -->
Exactly one of `config` (one file) and `config_tree` is required; release mode requires `config_tree`.

<!-- behavior:BHV-IMAGE-SNAPSHOT -->
`debian_snapshot` is required in release mode and optional in tracer mode, where it replaces the network as the package source.

<!-- behavior:BHV-IMAGE-SEED -->
`release_seed` is required only in release mode and must match the resolved `Seed=`.

<!-- behavior:BHV-IMAGE-EPOCH -->
`release_source_date_epoch` is a non-negative value, required only in release mode, that must match the resolved `SourceDateEpoch=`.

<!-- behavior:BHV-IMAGE-IMMUTABLE -->
Unsigned UKI and hash-only dm-verity are release-only, and verity requires the UKI.
A `Verity=hash` repart definition without `SizeMinBytes=` or `Minimize=` is rejected.
The verity projection checks split artifacts against the GPT and recomputes the complete hash tree, rejecting truncation, mutation, and nonzero padding; a minimized root may cover only the start of its partition if the rest is zero.
Inactive `_empty` slots are excluded.

<!-- behavior:BHV-IMAGE-SOURCES -->
`source_trees` stages typed trees at unique normalized relative paths and rejects traversal, aliases, collisions, and untyped values.

<!-- behavior:BHV-IMAGE-ROOTFS-PAYLOADS -->
`rootfs_payloads` installs typed files and trees at normalized absolute image paths, keeps declared executables and relative symlinks, and rejects aliases, collisions, traversal, and unsafe links.

<!-- behavior:BHV-IMAGE-IDENTITY -->
`image_id` and `image_version` expand Make variables, override `ImageId=` and `ImageVersion=`, and appear in `MkosiImageInfo` and the build metadata.
A version requires `image_id` and uses letters, digits, and `.` only.
`image_version_file` supplies the version at execution time with the same rule (plus one optional newline) and excludes `image_version`; it reaches mkosi, the slot-label check, the build metadata, and `sysupdate_payload`.

<!-- behavior:BHV-IMAGE-BASE -->
`mkosi_base` installs a release configuration's packages offline from its snapshot, exposes the root archive and default initrd through `MkosiBaseInfo`, requires a seed and non-negative epoch, rejects `ImageVersion=` and kernel modules initrd settings, and has no version input.
`mkosi_image(base = ...)` requires release mode and UEFI, rejects snapshot, seed, epoch, and `source_trees` attributes, and rejects configurations that install packages, configure the default initrd, or override `BaseTrees=` or `Initrds=`.
Its `MkosiImageInfo` matches a one-stage release, and a second version reuses the cached base.

<!-- behavior:BHV-SYSUPDATE-TRANSFERS -->
`sysupdate_transfers` validates the image id, a non-negative `boot_attempts` (zero installs UKIs without a boot counter), and at least two `instances`, and installs root, verity, and UKI transfers that use `PathRelativeTo=explicit` or, with an `http://` or `https://` `url`, `url-file` sources with `Verify=yes`, root-hash UUIDs, accept plain or xz-compressed partition files, and protect the running version.

<!-- behavior:BHV-TREE-SRC -->
`mkosi_config_tree.src` and `mkosi_source_tree.src` each resolve to exactly one file or directory and produce their typed provider.

<!-- behavior:BHV-TREE-EXECUTABLES -->
Both tree rules accept normalized `executable_paths`, which staging preserves; escaping paths are rejected.

<!-- behavior:BHV-TREE-ASSEMBLY -->
`mkosi_config_tree` assembles `src`, `srcs` at their package-relative paths minus `strip_prefix`, and `trees` keyed by destination into one directory with one action; `src` alone is used as is.
A tree may be shared by several destinations, such as `mkosi.extra` and `mkosi.initrd.conf/mkosi.extra`, and an `mkosi_config_tree` tree adds its `executable_paths`.
Directories merge, and a symlink may point to a directory that its own tree contributes to a merge; traversal, absolute paths, files outside `strip_prefix` or the listing package, duplicate files, files colliding with directories, and unknown executables fail during analysis where paths are known, and otherwise before anything is staged.
Source files that are, or lie below, a symlink in their package and source directories in `srcs` or `trees` fail before anything is staged.

<!-- behavior:BHV-BOOT-IMAGE -->
Both boot adapters require `MkosiImageInfo.raw_image`; the SeaBIOS adapter also requires `firmware = "bios"`.

<!-- behavior:BHV-BOOT-MARKERS -->
`readiness_marker` and every `shutdown_markers` entry are nonempty exact serial markers that gate readiness and clean shutdown.

<!-- behavior:BHV-BOOT-MACHINE -->
`machine_args` precede the adapter's firmware arguments: OVMF flash drives, or the SeaBIOS ROM and debug console.

<!-- behavior:BHV-BOOT-ACCELERATOR -->
`accelerator` on both boot adapters and `qemu_ovmf_smoke_test` defaults to `auto` (KVM when `/dev/kvm` is accessible, else TCG), accepts `tcg`, and rejects other values.
The accelerator QEMU selected is logged and is the first line of the boot evidence.

<!-- behavior:BHV-BOOT-DEADLINES -->
The QMP, boot, and shutdown deadlines are positive, and their sum plus cleanup fits the timeout category, boundary included.

<!-- behavior:BHV-BOOT-DIAGNOSTICS -->
`diagnostic_bytes` is positive and bounds retained failure diagnostics.

<!-- behavior:BHV-BOOT-TIMEOUT -->
The macro's `timeout` accepts `short`, `moderate`, and `long`, propagates to the test, and rejects other categories.

<!-- behavior:BHV-BOOT-LIFECYCLE -->
`progress_markers` are nonempty, must appear in order before readiness, and cannot be combined with `expected_failure_marker`.
`allow_reboot` keeps one QEMU process, its image snapshot, and firmware variables across reboots.
`read_only_shares` exposes directories as read-only virtio-9p shares with unique 1 to 31 character tags.
`http_shares` serves the files of targets at unique URL paths of `http://10.0.2.100/` on an otherwise isolated QEMU user network.

<!-- behavior:BHV-BOOT-SECURE-BOOT -->
`qemu_ovmf_boot_test(secure_boot = True)` boots Debian's Secure Boot capable OVMF with SMM and secure flash and an empty variable store, so the firmware starts in Setup Mode; the default keeps the toolchain's OVMF, and only Secure Boot tests download the firmware.
The configuration rule rejects Secure Boot firmware code without its variable store.

<!-- behavior:BHV-MANAGED-PYTHON -->
`managed_python_test` requires one Python `src`, accepts optional `data`, and runs on the managed interpreter with isolated user-site state and an empty child `PATH`.

## Provider contracts

<!-- behavior:BHV-SECURE-BOOT-OFFLINE -->
Secure Boot uses no key by default.
Typed providers separate the unsigned binary (the UKI or a PE file read from the release image's ESP, such as systemd-boot), a digest-, path- and certificate-bound signing request, the externally signed binary, and its verified import.
Production keys never enter Bazel; the ephemeral test key stays inside one uncached action that never runs remotely.
Import checks the exact signer, the SHA-256 signature, and byte equivalence to the request; signed responses are not reproducible.

<!-- behavior:BHV-SECURE-BOOT-IMAGE -->
`secure_boot_signed_image` rewrites only the ESP of a copy of a UEFI release image: it replaces every copy of each requested unsigned binary with its verified signed binary, adds validated `.auth` files to `/loader/keys/auto/` and sets `secure-boot-enroll` in `loader.conf`.
It rejects signed binaries without an unsigned copy, remaining unsigned PE files, missing PK, KEK or db files, malformed authenticated variables, and a db that does not trust the signer of every imported or already signed `*.efi` or boot entry binary on the ESP; the output is deterministic for the same inputs.

<!-- behavior:BHV-SYSUPDATE-PAYLOAD -->
`sysupdate_payload` requires a versioned image with an unsigned UKI and dm-verity, optionally substitutes a signed UKI bound to that image, names root and verity artifacts by their root-hash UUIDs, trims them to the bytes that dm-verity covers, optionally compresses them deterministically with xz, rejects mismatching GPT UUIDs, writes `SHA256SUMS` of the shipped files, and exposes `SysupdatePayloadInfo`.

<!-- behavior:BHV-SYSUPDATE-SIGNING -->
`sysupdate_signing_request` binds the SHA-256 of an unsigned payload's `SHA256SUMS`, its files, and the fingerprint of exactly one public OpenPGP certificate, and rejects secret keys.
`sysupdate_import_signature` accepts only exactly one detached signature that sqv verifies over that `SHA256SUMS` with that certificate, and returns the payload's `SysupdatePayloadInfo` with `signature`; `sysupdate_ephemeral_test_fixture` signs in one uncached, local action and outputs only public data.

<!-- behavior:BHV-IMAGE-PROVIDER -->
`MkosiImageInfo` has a fixed `format_version`, exposes every artifact role as `File` or `None`, keeps `image` as an alias of `raw_image`, projects each present artifact once through `DefaultInfo`, and exposes `firmware`, `image_id`, `image_version`, and `image_version_file`.

<!-- behavior:BHV-TREE-PROVIDERS -->
`MkosiConfigTreeInfo` and `MkosiSourceTreeInfo` expose `tree` and normalized `executable_paths`.

<!-- behavior:BHV-SNAPSHOT-PROVIDER -->
`DebianSnapshotInfo` exposes the snapshot identity, components, lock digest, repository, metadata, and package records from authenticated inputs.

<!-- behavior:BHV-SNAPSHOT-CONSUMER -->
`//mkosi/debian:generate_lock` resolves a consumer specification into a deterministic multi-component lock.
The lock records the digest of its normalized specification, so a `debian_lock` test fails without network access when the specification changed since the last `<name>.update`.
`debian_tools.snapshot` turns it into a repository with a computed lock digest and rejects duplicate or reserved names.
Release images install from the components selected by `Repositories=` and reject components absent from the snapshot.

<!-- behavior:BHV-DEBIAN-TOOLS-PROVIDER -->
`DebianToolsInfo` exposes the Debian tools identity, archive, launcher and runfiles, provenance, and component inventory.

<!-- behavior:BHV-MKOSI-TOOLCHAIN-PROVIDER -->
`MkosiToolchainInfo` exposes mkosi provenance, its runfiles, `pefile`, and the selected Python 3.14 runtime.

<!-- behavior:BHV-QEMU-TOOLCHAIN-PROVIDER -->
`MkosiQemuToolchainInfo` exposes QEMU, its system data, OVMF, and SeaBIOS with their provenance.

<!-- behavior:BHV-BOOT-PROVIDER -->
`QemuBootConfigInfo` exposes the validated timeout category, deadlines, and cleanup margin.

<!-- behavior:BHV-PARTITION-METADATA -->
Release `partition_metadata` validates both GPT copies, keeps slot numbers, and omits random disk and partition GUIDs.
Versioned dm-verity images require exactly one populated root and verity slot with `<id>_<version>` labels, allow larger-or-equal `_empty` slots, and record root-hash UUIDs.
BIOS images require one BIOS boot partition of at least 1 MiB.
Tracer images have no partition metadata.

<!-- behavior:BHV-REPRODUCIBILITY-PROJECTION -->
`mkosi_reproducibility_manifest` selects the raw image, build metadata, and partition metadata through `MkosiImageInfo` and embeds a normalized, content-addressed projection.

<!-- behavior:BHV-CANONICAL-DIGEST -->
The manifest's whole-image digest covers every byte except GPT disk and partition GUIDs and the checksums derived from them, and validates a versioned dm-verity image's A/B slot labels.

<!-- behavior:BHV-REPRODUCIBILITY-INDEPENDENCE -->
A one-stage release, a compressed erofs release with its update payload, and a two-stage base and finalization are built twice in clean, uncached output roots, and their manifests and digests must match.

## Actions, toolchains, and failures

<!-- behavior:BHV-IMAGE-ACTIONS -->
An image target registers staging when needed, one `MkosiImage` action, and normalized metadata; outputs are uncompressed raw disks.

<!-- behavior:BHV-RELEASE-RUNTIME -->
Release builds use only the authenticated snapshot, block the network, remove APT sources, reject host-dependent configuration, and record reproducibility and snapshot metadata.

<!-- behavior:BHV-SYSUPDATE-LIFECYCLE -->
A versioned UEFI image updates itself from a read-only payload into its `_empty` slots, boots the new release from its compressed erofs verity root, and blesses it at `boot-complete.target`.
A release whose health check fails falls back to the previous release.

<!-- behavior:BHV-TRACER-RUNTIME -->
Tracer builds use the pinned mkosi and Debian tools with local execution and no caching, and produce a valid raw image.
They need network access, unless `debian_snapshot` is set: then they install packages only from the snapshot with the network blocked.

<!-- behavior:BHV-TOOLCHAIN-PATHS -->
mkosi, Python, Debian tools, QEMU, and firmware come from registered toolchains, never from host executables.

<!-- behavior:BHV-EXTENSION-VALIDATION -->
The `mkosi` extension selects the default or one supported version, honors one root override, and rejects unsupported, conflicting, multiple-name, or dependency-owned-name requests.

<!-- behavior:BHV-CONSUMER-ISOLATION -->
rules_mkosi's Python 3.14 tools work regardless of the consumer's default Python version.
The bootstrap executables follow the `bootstrap_platform` flag without changing consumer targets, including with a first-priority C/C++ toolchain that cannot link statically.

<!-- behavior:BHV-ACTION-FAILURES -->
Failures keep tool output and are classified as kernel capability, toolchain, network, assembly, or VM failures with one remediation.
SeaBIOS failures distinguish a missing boot sector, GRUB failure, kernel or initrd failure, readiness timeout, and shutdown failure, and boot logs are kept as test outputs.

<!-- behavior:BHV-STAGING-FAILURES -->
Staging rejects collisions, duplicate sources, absolute or traversing destinations, escaping links, and invalid file roles before writing output.

<!-- behavior:BHV-SNAPSHOT-FAILURES -->
Snapshot staging rejects bad signatures, mismatched hashes, incomplete or misplaced indexes, malformed or duplicate records, unsafe paths, and digest mismatches.

## Why line coverage is not a target

Bazel does not produce coverage for Starlark, so `.bzl` files yield no meaningful LCOV.
This catalog is the coverage contract until that changes; see [Starlark coverage status](starlark-coverage.md).
