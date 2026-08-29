# Evaluation: Bazel tooling for bootable OS images

- **Status:** Accepted
- **Date:** 2026-08-29
- **Decision:** Prototype a clean-room Bazel integration for mkosi

## Context

The target is a Bazelmod project that produces bootable x86-64 Linux disk
images for heterogeneous physical machines. Images must support UEFI and
legacy BIOS. The initial question was whether an existing Bazel ruleset could
be adopted instead of creating `rules_mkosi`.

This is specifically about bootable disks. OCI images, root filesystem
archives, initramfs images, packages, and filesystem images are useful inputs,
but none alone supplies a partition table, EFI System Partition, kernel, and
bootloader.

## Ecosystem findings

No module was found in the Bazel Central Registry under the expected names
`rules_mkosi`, `mkosi`, `rules_disk_image`, `rules_bootable`, or `rules_iso`.
This establishes absence under the obvious names at the time of research, not
proof that no private or unexpectedly named implementation exists.

The closest BCR projects solve adjacent problems:

| Project | Output | Assessment |
|---|---|---|
| [`rules_oci`](https://registry.bazel.build/modules/rules_oci) | OCI images | Container image, not a bootable disk |
| [`rules_img`](https://registry.bazel.build/modules/rules_img) | OCI images | Container image, not a bootable disk |
| [`rules_distroless`](https://registry.bazel.build/modules/rules_distroless) | Package-derived root filesystems | Useful for locked package payloads; no disk or bootloader |
| [`rules_pkg`](https://registry.bazel.build/modules/rules_pkg) | tar, zip, deb, and rpm packages | Packaging primitive |
| [`rules_squashfs`](https://registry.bazel.build/modules/rules_squashfs) | SquashFS filesystems | Potential immutable filesystem component |
| [`linux.bzl`](https://registry.bazel.build/modules/linux.bzl) | Linux kernels | Potential kernel input; experimental |
| [`rules_qemu`](https://registry.bazel.build/modules/rules_qemu) | QEMU toolchains | Useful for test infrastructure, but not an image builder |
| [`systemd`](https://registry.bazel.build/modules/systemd) | systemd built with Bazel | Potential source of `repart` and `ukify`; exposed targets require evaluation |

`rules_docker` is an older container-image ruleset and is maintained only as
needed. Its own documentation recommends `rules_oci` for new container work.

## Constellation

[Edgeless Systems Constellation](https://github.com/edgelesssys/constellation)
contains the only substantial public Bazel-to-mkosi integration found during
the research. The implementation lives in
[`bazel/mkosi`](https://github.com/edgelesssys/constellation/tree/main/bazel/mkosi)
and includes:

- An `mkosi_image` rule.
- A toolchain accepting either a Bazel executable or a host path.
- A missing-toolchain fallback for unsupported platforms.
- A feature flag exposing whether mkosi is available.
- A wrapper that makes Bazel paths absolute before changing mkosi's working
  directory.
- Support for declared outputs and image build resource estimates.
- A local package directory pattern that prevents an implicit fallback to
  network repositories.

These are useful architectural ideas, but the implementation is not an
adoptable dependency:

- Constellation is archived and its mkosi rules have not evolved with recent
  mkosi releases.
- The rules are embedded in the monorepository and are not a standalone
  Bazelmod module.
- Tool acquisition and wrapper paths are tied to Nix/NixOS.
- Image actions explicitly disable remote execution and sandboxing; consuming
  targets also disable caching.
- The example image layout is UEFI-only.
- The repository uses the
  [Business Source License 1.1](https://github.com/edgelesssys/constellation/blob/main/LICENSE)
  without a separate permissive license for `bazel/mkosi`.

The project can inform a clean-room design, but its source should not be copied
into an Apache-2.0 rules project without legal review.

## mkosi capabilities relevant to the rule

[mkosi](https://github.com/systemd/mkosi) is an actively maintained
systemd project. Version 27 was current during this evaluation. It is a Python
application distributed from its source repository rather than PyPI.

Relevant capabilities from the
[mkosi manual](https://github.com/systemd/mkosi/blob/v27/mkosi/resources/man/mkosi.1.md)
include:

- `Format=disk` creates partitioned disk images through `systemd-repart`.
- `Bootloader=systemd-boot` or `Bootloader=grub` installs a UEFI boot path.
- `BiosBootloader=grub` may be enabled at the same time as `Bootloader=`.
- A BIOS boot partition uses GPT type UUID
  `21686148-6449-6e6f-744e-656564454649` and must be at least 1 MiB.
- Output formats also include UKI, ESP, tar, cpio, OCI, sysext, and portable
  service artifacts.
- `Snapshot=`, `ToolsTreeSnapshot=`, `SourceDateEpoch=`, and `Seed=` support
  reproducible inputs and identifiers.
- `CacheOnly=always`, `LocalMirror=`, and `PackageDirectories=` support
  network-independent builds when all package inputs are available locally.
- `SplitArtifacts=` can emit partitions, UKIs, roothashes, PCR data, and
  related lifecycle artifacts separately from a monolithic raw disk.

Important host constraints are Linux, recent kernel and systemd versions,
namespace availability, and host image-building utilities. Ubuntu AppArmor
restrictions on unprivileged user namespaces can block mkosi. Some
configurations require privileges, although offline repartitioning avoids
loop devices for many builds.

## Bazel boundary

A Bazel rule can provide:

- Declared application and configuration inputs.
- A pinned mkosi toolchain.
- Explicit image and metadata outputs.
- Correct invalidation when inputs change.
- Resource scheduling.
- Standard entry points for configuration, partition, and boot tests.
- A module extension for toolchain acquisition.

It cannot automatically make package-manager and disk-image operations
hermetic. Network access, mutable package caches, host namespaces, kernel
capabilities, and multi-gigabyte output artifacts remain concerns.

The initial execution policy should therefore be honest:

- Linux-only execution compatibility.
- No remote execution until a compatible worker platform is proven.
- Prefer unprivileged and offline image generation, but permit `no-sandbox`
  where namespace nesting requires it.
- Mark networked builds non-cacheable.
- Enable caching only for snapshot-pinned, offline builds with deterministic
  identifiers and verified package inputs.
- Prefer split partitions and UKIs as cache artifacts rather than only a large
  sparse raw disk.

## Decision

Implement the first integration in this repository, from scratch, against a
pinned mkosi release. Do not copy Constellation source.

Start with:

1. A Linux mkosi toolchain and Bazelmod module extension.
2. A small `mkosi_image` rule with explicit inputs and outputs.
3. A missing-toolchain path that keeps analysis working on unsupported hosts.
4. Configuration and partition-layout tests.
5. Explicit QEMU boot tests using OVMF and SeaBIOS.
6. An offline package mirror and reproducibility model before claiming remote
   cache safety.

Publishing to BCR is deferred until the interface has served real images and
the compatibility policy for mkosi releases is understood.

## Risks and validation gates

The first prototype must answer:

1. Can mkosi run as an unprivileged Bazel action on the actual CI workers?
2. Can the same content boot reliably through both OVMF and SeaBIOS?
3. Can release builds run with network egress disabled?
4. Which outputs are byte-reproducible across independent workers?
5. Is storing raw disks in the remote cache economical?
6. Which mkosi configuration surfaces belong in Starlark and which should
   remain in native mkosi configuration files?

