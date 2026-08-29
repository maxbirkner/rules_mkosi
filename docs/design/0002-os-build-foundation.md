# Evaluation: OS build foundation

- **Status:** Accepted
- **Date:** 2026-08-29
- **Decision:** Use mkosi with Debian for heterogeneous x86; reserve Yocto for fixed embedded products

## Context

The intended system replaces Ubuntu 22.04 on varied x86-64 machines, including
UEFI and legacy-BIOS systems. The choice is not merely between image-building
tools. It determines whether the project consumes an existing binary
distribution or assumes responsibility for building and maintaining a Linux
distribution from source.

## Product model

The default product model is a **curated Debian-derived appliance OS**, not a
new source distribution.

Under this model Debian remains responsible for:

- Building and integrating the base package ecosystem.
- A broad generic x86 kernel and firmware policy.
- Package-level security maintenance.
- Dependency resolution and architecture support.

This project remains responsible for:

- Package selection and configuration.
- Image and partition layout.
- Boot, signing, update, rollback, and recovery policy.
- Package snapshots and release reproducibility.
- Product SBOM, vulnerability response, and provenance.
- Hardware qualification.

This boundary preserves commodity-PC hardware coverage while still permitting
an immutable, image-based product.

## Candidate assessment

### mkosi and systemd-repart

[mkosi](https://github.com/systemd/mkosi) assembles packages from an existing
distribution into directory, archive, UKI, ESP, OCI, or partitioned disk
outputs. Its close integration with `systemd-repart`, UKIs, dm-verity, and
`systemd-sysupdate` makes it more than a generic rootfs script, but it remains
an image assembler rather than a distribution or fleet-management service.

Strengths:

- First-class Debian and Ubuntu support.
- Reuse of Debian's broad generic x86 kernel and firmware.
- UEFI and GRUB BIOS boot support.
- Reproducibility controls and offline repository support.
- Split update artifacts, dm-verity, UKI, and systemd-sysupdate integration.
- Small configuration surface compared with a source distribution builder.

Risks:

- Fast-moving configuration and command-line interface.
- No complete installer, update server, rollout service, or recovery system.
- Legacy BIOS receives less ecosystem testing than UEFI.
- Secure Boot, key management, package mirrors, and hardware qualification
  remain product responsibilities.

### KIWI NG

[KIWI NG](https://osinside.github.io/kiwi/) is the strongest alternative image
assembler. It supports Debian and Ubuntu as well as RPM distributions and has
mature concepts for UEFI, CSM/BIOS, OEM disks, live media, PXE, first-boot disk
expansion, and installation images.

KIWI should replace mkosi if qualification shows that mkosi's BIOS path is not
reliable enough, or if OEM installation and live/PXE workflows become primary
requirements. Its disadvantages are a larger framework, GPL-3.0-or-later
licensing, concentrated maintenance, and no native OTA lifecycle comparable
to mkosi's systemd-sysupdate integration.

### Yocto/OpenEmbedded

[Yocto/OpenEmbedded](https://www.yoctoproject.org/) is a complete
source-distribution construction system. It provides a strong signed task
graph, shared-state caching, cross-compilation, SDK generation, source
patching, license manifests, SPDX generation, long-term releases, and a large
embedded BSP ecosystem.

Yocto is the right answer when:

- Hardware is a small set of controlled and qualified boards.
- The silicon vendor supplies an OpenEmbedded BSP.
- Custom kernel patches, PREEMPT_RT, or out-of-tree drivers are central.
- The product needs a nonstandard libc, init system, or very small footprint.
- Full source provenance or a frozen toolchain is a compliance requirement.
- A dedicated platform team will maintain the distribution for 10-15 years.

It is not the default for arbitrary commodity x86. Doing so makes the product
team responsible for kernel configuration, firmware selection, source recipes,
backports, and integration breadth currently inherited from Debian.

BitBake is also already a build graph, scheduler, signature engine, and cache.
Running it under Bazel should remain a single orchestration boundary rather
than attempting to mirror BitBake tasks as Bazel actions.

### ISAR

[ISAR](https://github.com/ilbers/isar) combines BitBake workflows with Debian
binary packages. It is a credible middle ground when a product needs BSP,
custom-kernel, and industrial image discipline while retaining Debian.

ISAR becomes a finalist if fixed vehicle or HPC hardware requires extensive
kernel customization across variants. It otherwise adds BitBake complexity
without enough benefit over mkosi.

### Buildroot

[Buildroot](https://buildroot.org/) is well suited to a compact, fixed-purpose
system where a team wants an understandable Kconfig and Make-based source
build. It is less suitable here because its generic PC configurations are
samples rather than a comprehensive hardware policy, its incremental rebuild
model requires care after configuration changes, and its reproducibility
support is less mature than Yocto's.

Choose Buildroot only for a small, tightly controlled appliance where build
simplicity and footprint matter more than package-level field maintenance.

### PTXdist

[PTXdist](https://www.ptxdist.org/) is a capable embedded Linux BSP and
platform builder with a particularly close relationship to
[RAUC](https://rauc.io/). It is strongest when used with Pengutronix expertise
and supported hardware platforms. Its generic modern PC baseline and desktop
hardware ecosystem are too weak for the default use case.

### RPM image stacks

[osbuild](https://www.osbuild.org/) and Image Builder are strong declarative
image pipelines in the Fedora/RHEL ecosystem but do not provide an equivalent
Debian package-composition path.

[bootc](https://bootc-dev.github.io/bootc/) provides an attractive OCI-native,
transactional OS model with rollback. Its strongest supported path is
RPM-based. Debian bootc efforts were not mature enough during this evaluation
to justify making them the foundation.

### Adopt instead of build

[Flatcar Container Linux](https://www.flatcar.org/) is the strongest control
option if the machines can become container hosts. It already provides an
immutable OS, A/B updates, rollback, and a managed lifecycle.

[Talos Linux](https://www.talos.dev/) is even more purpose-built for
Kubernetes, but has no normal shell, SSH administration, or conventional host
services. It becomes the leading option only if every hardware-facing service
can run as a Kubernetes workload or supported system extension.

These options should remain in the evaluation because deleting the custom OS
pipeline is less expensive than optimizing it.

## Comparative decision

For heterogeneous general-purpose x86, the most important criteria are
hardware support, inherited maintenance, reliable updates, time to production,
BIOS support, and project longevity. Bazel integration is intentionally a
lower-weight criterion because all complete image builders become a coarse
action at the Bazel boundary.

The resulting order is:

1. mkosi with Debian.
2. Flatcar, if an existing container host is sufficient.
3. KIWI NG with Debian.
4. debos/mmdebstrap.
5. bootc with an RPM base.
6. Yocto/OpenEmbedded.
7. Buildroot.

For fixed embedded hardware with a 10-15 year life, source patching, strict
provenance, and a small footprint, the ordering changes:

1. Yocto/OpenEmbedded with RAUC.
2. ISAR with RAUC or EFI Boot Guard.
3. PTXdist with RAUC and vendor support.
4. mkosi with Debian.

The fleet may justify two pipelines if it contains both truly heterogeneous
PCs and a stable, high-volume embedded SKU. That split should be based on
hardware and lifecycle requirements, not organizational naming.

## Update architecture

The update mechanism must be chosen before finalizing the partition layout.

### UEFI tier

Use:

- systemd-boot.
- Signed Unified Kernel Images.
- An immutable EROFS or SquashFS `/usr` or root partition.
- dm-verity with an offline-signed root hash.
- Two update slots provisioned by `systemd-repart`.
- `systemd-sysupdate` for partition and UKI transfer.
- Boot counting and a product-specific health check before blessing a boot.
- Optional TPM measurement and sealing.

The [systemd ParticleOS](https://github.com/systemd/particleos) repository is
useful architectural prior art for this combination. It is not a stable
dependency and does not promise backward compatibility.

### Legacy-BIOS tier

Use:

- GRUB with a GPT BIOS boot partition.
- A conventional kernel and initrd.
- The same userspace content as the UEFI image where possible.
- An explicitly designed A/B state machine using GRUB environment state.
- RAUC's GRUB backend as the leading update candidate.

Legacy BIOS cannot provide the same UKI, Secure Boot, measured-boot, and TPM
chain as UEFI. It should be a documented compatibility tier with a retirement
plan, not the security baseline for every machine.

### Update system findings

| System | Assessment |
|---|---|
| [`systemd-sysupdate`](https://www.freedesktop.org/software/systemd/man/latest/systemd-sysupdate.html) | Best native fit for mkosi, repart, UKIs, and UEFI boot counting; no binary delta and no turnkey BIOS rollback |
| [RAUC](https://rauc.io/) | Best open BIOS-capable choice; signed bundles, interruption safety, streaming, and GRUB/EFI backends |
| [SWUpdate](https://sbabic.github.io/swupdate/) | Most flexible, but leaves more policy and integration to the product |
| [Mender](https://mender.io/) | Strong Debian-family A/B and fleet-management option if purchasing or adopting its management plane is acceptable |
| bootc/OSTree | Strong transactional and OCI model; currently a better fit for RPM-derived systems |

## Recommended architecture

| Layer | Choice |
|---|---|
| Image assembler | mkosi v27, pinned by archive and checksum |
| Distribution | Debian 13 trixie |
| Kernel | Debian generic amd64 kernel unless a measured requirement forces a custom build |
| Package source | Immutable Debian snapshot mirrored locally with checksums |
| Release build | Offline; no implicit package repository access |
| Disk | GPT with explicit repart definitions |
| Cached artifacts | Partitions, UKIs, verity data, manifests, and compressed release image |
| UEFI | systemd-boot, signed UKI, dm-verity, systemd-sysupdate |
| BIOS | GRUB, conventional kernel/initrd, separately qualified rollback path |
| Writable state | Separate persistent partition; keep system content immutable |
| Signing | Offline or HSM-backed stage using split artifacts |
| Testing | OVMF, SeaBIOS, update interruption, rollback, and representative real hardware |
| Bazel | Build payloads, pin inputs, invoke assembly, validate outputs, and run tests |

## Proof-of-concept decision gate

Compare no more than three paths:

1. mkosi v27 with Debian 13.
2. KIWI NG with Debian 13.
3. Flatcar LTS as the “do not build an OS” control.

Required acceptance criteria:

1. Boot with functional storage and networking on every representative
   hardware family, including BIOS-only machines.
2. Boot under both OVMF and SeaBIOS.
3. Build without privileged containers or host loop devices.
4. Reproduce immutable partitions byte-for-byte from pinned inputs.
5. Complete release builds without network access.
6. Update from A to B and automatically roll back after a forced failed health
   check.
7. Survive hard power interruption during download, write, activation, first
   boot, and health confirmation.
8. Reject modified immutable content under Secure Boot and dm-verity on UEFI.
9. Measure cold and warm build times, update payload sizes, and porting effort
   for every image role.

mkosi remains the default unless it fails hardware boot, BIOS boot, or
power-loss recovery. A BIOS-only failure should first trigger the two-tier
design or KIWI evaluation. Yocto should enter the bake-off only when a fixed
hardware product and source/BSP requirements are confirmed.

