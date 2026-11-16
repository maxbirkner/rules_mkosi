# Design: arm64 images, built natively and cross-built from x86-64

- **Status:** Accepted
- **Date:** 2026-11-15
- **Issue:** [#206](https://github.com/maxbirkner/rules_mkosi/issues/206)

## Context

Embedded boards are mostly arm64, for example a board whose vendor kernel a consumer installs through `extra_packages`.
Today the Debian tools toolchain, the snapshot locks, the partition metadata, the UKI checks and the boot tests assume x86-64.
Most consumers build on x86-64 machines and CI runners, some also have arm64 runners.

## Decisions

- The target architecture is the architecture of the image's `debian_snapshot`; there is no new attribute and no platform transition.
- A lock resolves one architecture; arm64 gets its own locks and snapshot repositories.
- The execution platform selects the mode through toolchain resolution: an x86-64 platform cross-builds, an arm64 platform builds natively.
- Cross builds run the image's foreign maintainer scripts through the pinned static `qemu-aarch64` of rules_qemu, registered with the `F` flag in a `binfmt_misc` instance private to the action's user namespace.
  They need Linux 6.7 but neither root nor any host registration.
- Boot tests pick `qemu-system-aarch64` and the pinned AAVMF firmware from the image's architecture.

This answers the issue's open questions: one Debian tools toolchain per execution platform, with the target architecture carried by the snapshot, and cross-building is not a default or a fallback but what an x86-64 execution platform does.

## Target architecture

`DebianSnapshotInfo.architecture` already names the package architecture, `extra_packages` are validated against it, and the build metadata records it.
`mkosi_image` and `mkosi_base` derive the image architecture from it, and `MkosiBaseInfo` carries it to the finalizing `mkosi_image`.
A new `MkosiImageInfo.architecture` field (and the same field in `MkosiBaseInfo`) exposes it to boot tests and consumers.

Like `Distribution=`, `Release=` and `Snapshot=`, a configuration built from a snapshot must resolve `Architecture=` to the snapshot's architecture (`x86-64` for `amd64`, `arm64` for `arm64`).
The release validation rejects any other value with a `must resolve to ...` error, so a configuration is never silently overridden.
An arm64 configuration therefore states `Architecture=arm64`.

Foreign architectures need `debian_snapshot`.
A network tracer build without one keeps building for the execution platform's architecture, as today.

Rejected alternatives:

- **An `architecture` attribute** would duplicate the snapshot's architecture and could contradict it.
- **Bazel platforms and transitions** describe compiled code.
  An image's architecture is fixed by its package set, and image actions resolve only execution-platform toolchains.
  A transition would need platforms that rules_mkosi defines and consumers must match, and it would rebuild the consumer's dependencies in a configuration they did not ask for.

Images stay buildable under any target platform, because image rules and their toolchains carry only execution constraints.
A `rootfs_payloads` binary must be built for the image's architecture by the consumer, for example with `platform_transition_filegroup` of bazel_lib or under `--platforms`; rules_mkosi cannot know the consumer's C/C++ platform.

## Packages and locks

A lock keeps resolving exactly one architecture.
The spec's `archs` accepts `["amd64"]` or `["arm64"]`, the generator reads `binary-<arch>` and `binary-all` indexes, and the snapshot repository verifies and serves those indexes.
`debian_tools.snapshot` is unchanged: the lock's architecture defines the repository's.

A consumer that builds both architectures keeps two specs and locks, such as `debian.amd64.lock.json` and `debian.arm64.lock.json`, with one `debian_lock` target and one snapshot tag each.

A multi-architecture lock was rejected:

- `DebianSnapshotInfo`, the `extra_packages` check and the lock digest in the build metadata all describe one architecture.
- The closures differ per architecture (`linux-image-arm64`, `grub-efi-arm64-bin`), so the spec would need per-architecture package lists anyway.
- Separate repositories let Bazel download only the architecture that a build uses.

The built-in `mkosi/debian/debian13.arm64.spec.json` and `debian13.arm64.lock.json` resolve the arm64 Debian tools closure at the same snapshot as the amd64 one.
Like the amd64 lock, it serves two purposes: the built-in `@mkosi_debian_snapshot_arm64//:repository`, and the package set of the native arm64 Debian tools tree.
`refresh_debian_tools` moves both locks together and records the arm64 provenance.
The arm64 archive digest can be computed on x86-64, because building the archive only unpacks packages.

## Execution modes

| Execution platform | Image | Mode |
| --- | --- | --- |
| Linux x86-64 | amd64 | Native, unchanged. |
| Linux x86-64 | arm64 | Cross: amd64 Debian tools, arm64 maintainer scripts under `qemu-aarch64`. |
| Linux aarch64 | arm64 | Native: arm64 Debian tools. |
| Linux aarch64 | amd64 | Not supported; fails during analysis. |

The rule compares the snapshot's architecture with `DebianToolsInfo.architecture` during analysis.
If they differ, it takes the emulator for the snapshot's architecture from the toolchain or fails with a message that names the supported execution platforms.

### Cross from x86-64

In a cross build only foreign code is emulated: dpkg's maintainer scripts and the triggers that run in the image root.
APT, dpkg, systemd-repart, the mkfs tools, ukify and the signing tools run natively from the amd64 Debian tools.
mkosi takes `systemd-bootaa64.efi` and `linuxaa64.efi.stub` from the image root, so the tools tree needs no arm64 boot files.

**What the toolchain ships.**
The x86-64 Debian tools toolchain gains `DebianToolsInfo.user_mode_emulators`, mapping `arm64` to rules_qemu's static `qemu-aarch64` (QEMU 11.0.0, about 2 MB, pinned by rules_qemu's SHA-256).
It is an input of every cross-build action, so a new emulator changes the cache key.

**Registration.**
A host registration is global host state that only root can change, and it would run an unpinned host emulator inside release builds.
Instead, a small static bootstrap helper wraps the mkosi process of a cross build:

1. It creates a user namespace that maps the caller's own uid and gid, and a mount namespace.
2. It mounts a `binfmt_misc` instance, which since Linux 6.7 is private to that user namespace.
3. It registers the emulator for the aarch64 ELF magic and mask of QEMU's `qemu-binfmt-conf.sh`, with the flags `F` (open the interpreter now, so it works inside chroots that do not contain it) and `P` (preserve `argv[0]`).
4. It executes mkosi's Python with an unchanged, unprivileged identity.

mkosi's own user namespaces are children of that namespace, and the kernel looks up handlers in the nearest ancestor namespace with an instance, so maintainer scripts find the emulator, and the host's registrations are not consulted.
The instance disappears with the action.
Native builds do not use the helper.

This was verified on Linux 7.0 inside Bazel's Linux sandbox, with Ubuntu's restriction of unprivileged user namespaces enabled: an unprivileged process mounted the instance, registered a static interpreter with `F`, and a nested user and mount namespace executed a file through it inside a chroot without the interpreter.
The instance listed only the new entry, not the host's registrations.

**Host contract and preflight.**
The [host-kernel contract](0004-host-kernel-contract.md) gains a check that applies only to cross builds:

| Check | Requirement | Remediation |
| --- | --- | --- |
| Private `binfmt_misc` | In the action's user namespace, `binfmt_misc` mounts, accepts an `F` registration and executes a file through it. | Use Linux 6.7 or newer; load the `binfmt_misc` module if it is not built in; or build on an arm64 execution platform. |

The helper reports a failed mount or registration as `KERNEL_CAPABILITY_FAILURE` with one `Action:` line, distinguishing a kernel older than 6.7 (the mount returns `EPERM`) from a missing `binfmt_misc` file system (`ENODEV`).
A new host test runs a small static aarch64 program, built by the llvm module, through the helper and the pinned emulator; `--config=kernel_preflight` runs it next to the existing preflight.
The minimum kernel stays 5.12 for native builds.

**CI** registers nothing.
The x86-64 runners need Linux 6.7, which the kernel preflight step verifies; the GitHub-hosted Ubuntu 22.04 runners use 6.8 kernels.

### Native arm64

The native mode needs an arm64 variant of every execution-platform input:

- an arm64 Debian tools tree from the arm64 lock and its toolchain `@mkosi_debian_tools//:linux_aarch64`;
- python-build-standalone's static `aarch64-unknown-linux-musl` interpreter for the launcher;
- the static bootstrap executables built for a Linux aarch64 musl platform, and a bootstrap execution platform that follows the host, so that an arm64 host does not schedule the llvm module's x86-64 compiler;
- the architecture-specific paths that the launcher, the namespace runner, the tree extractor and the Secure Boot helper's `libfaketime` hard-code today;
- a QEMU toolchain for arm64 execution platforms from rules_qemu's `linux_arm64` prebuilts.

## Boot artifacts

- **Partitions:** systemd-repart already receives `--architecture` from mkosi, so `Type=root` becomes `root-arm64`.
  The partition, dm-verity and sysupdate metadata look up the root, verity and verity signature type GUIDs by architecture instead of using the x86-64 ones, and sysupdate transfers name `root-arm64` partitions.
- **Boot loader and UKI:** `systemd-bootaa64.efi`, `BOOTAA64.EFI` and an arm64 UKI from `linuxaa64.efi.stub`, with the dm-verity root hash, as for x86-64.
- **Secure Boot:** signing requests, `systemd-sbsign` and `secure_boot_signed_image` treat PE files independently of their machine type; artifact tests verify the signed arm64 UKI and boot loader.
- **BIOS** stays amd64-only and already rejects other snapshots.

A reusable fixture package `//mkosi/tests/arm64` holds an arm64 release configuration with UKI, `Verity=hash`, A/B partitions and update payloads, built from `@mkosi_debian_snapshot_arm64`.
The device tree work of [#207](https://github.com/maxbirkner/rules_mkosi/issues/207) extends that fixture instead of creating its own.

## Boot tests

The QEMU toolchain provides one emulator and UEFI firmware per guest architecture: `qemu-system-x86_64` with OVMF, and rules_qemu's `qemu-system-aarch64` (about 7 MB) with the `aarch64/code.fd` and `aarch64/vars.fd` that the pinned `edk2-stable202605-r1` archive already contains, each pinned by SHA-256.
`qemu_ovmf_boot_test` selects them from `MkosiImageInfo.architecture`, so one rule boots both architectures.

For arm64 guests the defaults are `-machine virt`, the PL011 serial console instead of `isa-serial`, and `-cpu max,pauth-impdef=on` under TCG, whose implementation-defined pointer authentication is much cheaper to emulate, or `-cpu host` under KVM.
`accelerator = "auto"` tries KVM only when the guest matches the execution platform's CPU, and otherwise uses TCG without a failed KVM attempt.
TCG is several times slower than KVM, so the arm64 fixtures set longer boot deadlines and a `long` test timeout; the implementation records measured durations.
`qemu_seabios_boot_test` and `secure_boot = True` reject arm64 images during analysis.

## CI and reproducibility

| Where | arm64 coverage |
| --- | --- |
| Root suite, Ubuntu 22.04 x86-64 | Cross-builds `//mkosi/tests/arm64` with `//...`, runs its artifact tests, its UEFI boot test and its A/B update test under TCG. |
| Consumer suite (`e2e/smoke`) | Locks a consumer arm64 snapshot, cross-builds a release image and boots it. |
| Kernel preflight step | Also runs the cross-build preflight. |
| Release reproducibility step | Adds the arm64 fixture's reproducibility manifest to `ci/verify-release-reproducibility.sh`. |
| New `arm64` job, `ubuntu-22.04-arm` | Kernel preflight, then natively builds and boots `//mkosi/tests/arm64` and runs the Debian tools toolchain tests; required by `CI conclusion`. |

GitHub's arm64 runners are not known to expose `/dev/kvm`, so the native job may boot under TCG too; the boot evidence records the accelerator.
If the A/B update test takes too long under TCG on x86-64, it moves to the native job, and the root suite keeps the single boot.

Reproducibility is claimed per execution platform: two clean cross builds, or two clean native builds, produce the same image.
Cross- and natively built images run different tool binaries, so their actions have different cache keys, and their byte equality is not claimed.

## Implementation order

Each step is one pull request that passes CI on its own.

1. **arm64 snapshot locks:** the generator and the snapshot repository for one architecture of `amd64` or `arm64`, the built-in arm64 lock and `@mkosi_debian_snapshot_arm64`, `refresh_debian_tools` for both locks, and a consumer arm64 lock in `e2e/smoke`.
2. **Cross builds:** `Architecture=` validation, `DebianToolsInfo.user_mode_emulators`, the `binfmt_misc` helper and its preflight, the host-contract update, and a minimal arm64 image in `//mkosi/tests/arm64` with an artifact test.
3. **arm64 release artifacts:** architecture-aware partition, dm-verity and sysupdate metadata, `MkosiImageInfo.architecture`, the reusable UKI, verity and A/B fixture, Secure Boot signing tests, the reproducibility entry and an `e2e/smoke` arm64 release image.
4. **arm64 boot tests:** the per-architecture QEMU toolchain, the arm64 machine defaults, the fixture's boot and A/B update tests, and the consumer boot test.
5. **Native arm64:** the arm64 Debian tools tree and toolchain, the aarch64 bootstrap and its execution platform, the QEMU toolchain for arm64 hosts, and the `arm64` CI job.
6. **Documentation:** requirements, troubleshooting and the behavior catalog for arm64; closes #206.

Steps 2 to 4 satisfy the issue's acceptance criteria on x86-64 CI; step 5 adds native builds.

## Out of scope

- Other architectures, such as armhf or riscv64, and amd64 images on arm64 hosts, although the emulator map would extend to them.
- Host `binfmt_misc` registrations, and cross builds on kernels older than 6.7.
- Foreign images from network tracer builds without `debian_snapshot`.
- Byte equality between cross- and natively built images.
- Secure Boot enforcement in arm64 boot tests, which needs a pinned Secure Boot capable AAVMF build.
- Device trees ([#207](https://github.com/maxbirkner/rules_mkosi/issues/207)) and non-UEFI boot flows such as U-Boot without EFI.
- Building `rootfs_payloads` for the image's architecture, and checking their ELF machine type.
- Physical hardware qualification of arm64 boards.

## Risks to verify during implementation

- mkosi steps that run in the image root beyond maintainer scripts, such as `ldconfig` or `depmod`, may need emulation or the image's own binaries.
- ukify must accept Debian's compressed arm64 `vmlinuz` when it builds the UKI.
- Emulated maintainer scripts must not make the image differ between two builds, for example through byte-compiled Python files.
- The `ubuntu-22.04-arm` runner must pass the host-kernel contract; otherwise the native job documents the gap and the cross path remains the release path.

## Outcome

The plan was implemented in #223, #224, #225, #227, #228, #229, #232, #235, #238, #245 and the documentation pull request that closes #206; step 5 was split into the bootstrap platform (#235), the native build (#238), and native boot tests (#245).

- All four risks resolved: emulated `ldconfig`, `depmod` and maintainer scripts work, ukify accepts Debian's arm64 kernel as is, two cross builds produce identical reproducibility manifests in CI, and `ubuntu-22.04-arm` passes the host-kernel contract.
- The arm64 A/B update test runs in `e2e/smoke` instead of the root suite, because the built-in snapshot lacks `systemd-container`, which provides `systemd-sysupdate`, and `gpg`; it covers update, reboot and blessing, not the rollback that the amd64 test already proves.
- The UEFI firmware does not mount an ESP whose FAT32 file system has fewer than 65525 clusters, and systemd-repart formats it with 4 KiB clusters, so the arm64 fixtures use 512 MiB ESPs.
- arm64 guests need 1 GiB, because Debian's arm64 kernel stub fails to load the UKI's larger initrd with 512 MiB.
- GitHub's arm64 runners expose no `/dev/kvm`, so native boot tests run under TCG there as well.

Measured durations (GitHub-hosted runners):

| Test | Duration |
| --- | --- |
| arm64 UKI fixture boot, TCG on x86-64 | 73 to 96 s |
| Consumer arm64 image boot, TCG on x86-64 | 52 to 107 s |
| arm64 A/B update and blessing, TCG on x86-64 | 155 to 216 s |
| arm64 UKI fixture boot, TCG on arm64 | 57 s |
| Native arm64 job: preflight, build of both fixtures, tests | about 5 min |
