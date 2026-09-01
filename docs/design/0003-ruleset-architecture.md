# Design: ruleset repository, testing, and release architecture

- **Status:** Accepted
- **Date:** 2026-08-29

## Goals

The repository must:

- Be a Bazelmod-native ruleset suitable for eventual BCR publication.
- Keep the public API small and separate from implementation details.
- Test providers and actions during analysis.
- Test generated artifacts during execution.
- Include an independent consumer module using `local_path_override`.
- Keep portable analysis coverage separate from the dedicated-runner real-image
  test.
- Evolve toward Bazel-provided toolchains and offline image inputs.

## Module policy

`MODULE.bazel` intentionally leaves `version` unset. The BCR publishing
workflow patches the release version into the registry copy. Setting a source
version causes problems for consumers using non-registry overrides.

`compatibility_level` is also omitted. It became a deprecated no-op in recent
Bazel 8 and 9 releases. Breaking releases must instead provide explicit
migration diagnostics and documentation.

The supported baseline is Bazel 8.5.1. The rolling policy supports the
current and previous Bazel LTS majors, currently Bazel 8 and 9.
`.bazelversion` pins the lockfile-generating development version.

## Public API boundary

Consumers load rules and providers only from `//mkosi:defs.bzl`. Files below
`//mkosi/private` are implementation details. The toolchain type is public
because registration and advanced integrations need a stable label.

`mkosi_image` exposes a stable `MkosiImageInfo` output contract. Its
`format_version` is always `mkosi-image-v1`, and its `raw_image`, `manifest`,
`partition_metadata`, `uki`, and `build_metadata` fields are each a `File` or
`None`; consumers select fields rather than infer roles from artifact names.
The current disk/raw mode provides `raw_image` and
the normalized JSON `build_metadata` projection, and sets the future manifest,
partition, and UKI fields to `None`. Its legacy `image` field remains an exact
compatibility alias for `raw_image`. `DefaultInfo.files` contains each
non-`None` provider artifact once, with no ordering guarantee; existing
consumers must not assume it is a singleton. The action invokes the pinned mkosi v27 executable and the pinned Debian 13
tools tree through registered toolchains. The toolchain crosses Bazel's cache
boundary as an authenticated regular tar artifact; the image wrapper extracts
it into action-local workspace storage so merged-`/usr` symlinks never need to
be replayed as a directory artifact. The explicit `mode` API defaults to
networked `"tracer"` mode, which is non-cacheable and not remote- or
offline-hermetic. `"release"` mode requires `DebianSnapshotInfo`, materializes
the authenticated local APT tree, blocks network access, and omits the
tracer-only `no-cache` requirement. Release callers must provide
`config_tree`, `release_seed`, and `release_source_date_epoch`; execution
resolves the pinned mkosi configuration, rejects filesystem paths outside its
declared staged inputs, and rejects it unless the values match `Seed=` and
`SourceDateEpoch=`. A narrow release wrapper supplies deterministic passwd,
group, hosts, and NSS sandbox inputs rather than mkosi's host `/etc` defaults.
The stable provider remains `mkosi-image-v1`; its normalized metadata advances
to `mkosi-image-build-metadata-v2`, adding the release mode, reproducibility
inputs, and authenticated snapshot identity/lock digest. The release action
retains `no-remote-exec` pending execution-platform qualification, but may use
local and remote action caches. If APT is installed, release mode removes its
persistent package-source files rather than embedding a mutable network mirror.
The tracer action forces disk/raw/uncompressed output
and disables split artifacts; configuration files cannot redirect the declared
artifact or select a custom format. The legacy `config` attribute accepts
exactly one file. Complete
configuration directories use the explicitly typed `config_tree` provider,
which preserves `mkosi.conf.d/`, `mkosi.profiles/`, and `mkosi.extra/`.
`source_trees` is an explicitly typed normalized-relative-destination map;
each declared directory is staged at its map key, preserving paths used by
`BuildSources`. A single-file config remains compatible with existing
callers, while adding source trees stages that file at its basename so
relative references remain stable. Tree providers explicitly list executable
paths because Bazel input roots do not preserve source mode bits. Staging
actions consume only their declared labels and use deterministic map ordering.
Their manifest preflight rejects
path collisions, source aliases, and escaping links before writes; staging and
the Bazel input-root materialization normalize timestamps and permissions while
preserving valid relative links and executable bits.

The toolchain provider carries the pinned mkosi executable and complete
runfiles, a Bazel-managed Python 3.14 runtime, the optional `pefile` dependency
needed by mkosi's bootable PE inspection paths, and source provenance
(immutable URL and SHA-256 integrity). The generated repository selects that
runtime through `@rules_python//python:toolchain_type`; the dependency module
registers a deterministic CPython 3.14 default, while a root module can
register another compatible in-build 3.14 runtime at normal toolchain
precedence. Host-path runtimes and mismatched major/minor versions fail during
analysis. QEMU and firmware remain outside this image-building action and are
supplied by their separate toolchain.

The Debian launcher deliberately does not use that replaceable runtime. Its
first process must remain executable before a host or packaged dynamic loader
is trusted, so a pinned static CPython 3.14.7 runtime and a fully static native
bootstrap form a separate boundary. The native code uses rules_cc's runfiles
implementation to locate only the static interpreter and generated Python
stub, sanitizes inherited process state, and performs direct `execv(...,
"-I", ...)`. The stub is Python source even though it contains a convenience
shebang; that shebang is never used. The Click command owns argument parsing,
runfile/configuration resolution, archive authentication and extraction, and
namespace-runner orchestration. The separate static namespace runner retains
exclusive ownership of user/mount/PID/IPC/UTS setup, descriptor-only typed
mounts, pivoting away from the host root, and packaged-loader execution.

## Test layers

### Analysis tests

`bazel_skylib` `analysistest` inspects the configured target without executing
the action. It verifies:

- `MkosiImageInfo` is present and every optional-output combination preserves
  field/`DefaultInfo` correspondence.
- Provider fields and absent artifacts are correct.
- The raw-image and normalized-metadata projections are stable.
- Toolchain resolution selected the expected toolchain.
- The expected mkosi action and normalized-metadata projection were registered.

Analysis tests are the preferred Bazel mechanism for testing rule internals.
They are fast and isolate Starlark behavior from external tools.

### Artifact tests

Real disk images must never be checked in or compared directly. The real-image
artifact validator checks the GPT signature, a Linux x86-64 root partition,
CRC-valid primary and backup metadata, and ext4 allocation metadata. It uses
the image file descriptor's `SEEK_DATA`/`SEEK_HOLE` ranges to prove that the
root inode's bitmap-marked directory extent is physically allocated, without
booting the image. Future rules will derive reviewable text or JSON projections
and compare those instead:

- mkosi's effective configuration.
- Partition tables and GPT type UUIDs.
- Filesystem and verity metadata.
- UKI sections and signatures.
- Reproducibility across repeated builds.

Inspection binaries must be supplied through Bazel toolchains rather than
assumed to exist on the runner.

The checked-in tracer configurations fix `Seed=` and `SourceDateEpoch=` to
remove two known sources of variation. This does not claim full image
reproducibility while target packages are acquired over the network.

### Consumer module

`e2e/smoke` is an independent Bazel module. It depends on `rules_mkosi` through
`local_path_override`, registers the public module extension and toolchain,
consumes both a minimal configuration and a typed configuration/source tree
through the public `mkosi_image` rule. Its image builds and semantic artifact
tests run in the default consumer suite.

The consumer registers a recognizable CPython 3.14 wrapper ahead of the
dependency default. An analysis test inspects rules_mkosi's resolved
interpreter field, and executable tests run mkosi and the direct managed test
launcher with that runtime. This validates the ruleset's consumer-selection
boundary; it is not a generic test of Bazel's toolchain algorithm.

A nested `MODULE.bazel` does not stop root `//...` traversal. `.bazelignore`
therefore excludes `e2e/`, and CI invokes the consumer from its own working
directory. The consumer also selects `MkosiImageInfo.build_metadata` through a small
consumer-owned rule and validates the resulting JSON, rather than depending on
its filename or default output ordering. The consumer must remain in release archives because BCR runs it as
the module's test project.

### Future boot tests

Issue 8 now provides one UEFI/OVMF TCG boot test for the Debian tracer. Issue
19 extracts it as the public `qemu_ovmf_boot_test` adapter. It consumes the
public image through Bazel dependency edges, waits for a deterministic systemd
hostname marker on guest serial output, and requires the guest's clean
systemd power-off markers before accepting the QEMU exit. The adapter creates a native direct-ELF managed-Python launcher with a private
bootstrap rather than a shell wrapper; the bootstrap clears `PATH` before
executing the lifecycle source, and its runfiles include the complete
registered Python runtime. Its child QEMU therefore receives an empty `PATH`.
Before guest classification, the runner completes a bounded QMP greeting and
capabilities handshake, so QEMU
initialization/argument failures are distinct from firmware and guest
failures. The lifecycle accepts machine arguments, exact markers, deadlines,
and diagnostic retention as attributes and contains no UEFI logic; OVMF flash
arguments belong only to the adapter.

The production test hierarchy will later add:

1. Content tests against mounted or userspace-inspected filesystems.
2. Separate OVMF and SeaBIOS QEMU boots.
3. A serial-console readiness protocol with deterministic timeout and shutdown.
4. Update, failed-health-check, and automatic rollback tests.
5. Power interruption tests outside ordinary BCR workers.
6. Representative physical-hardware qualification.

QEMU, firmware, and inspection tools must be resolved as Bazel toolchains.
Real image jobs may require dedicated Linux runners even when the tools
themselves are pinned.

## CI

GitHub Actions runs the root and consumer suites against pinned Bazel 8.5.1
and 9.2.0. Bazel 8 validates the committed lockfiles strictly; Bazel 9 uses
lockfile mode off only for compatibility commands and never rewrites them.
Actions are pinned by commit SHA, permissions default to read-only, and
concurrent superseded branch builds are cancelled. A stable conclusion job can
be used for branch protection.

The weekly scheduled run detects breakage from rolling Bazel releases and
external dependency changes. Both committed lockfiles are generated and
validated with Bazel 8.5.1. Bazel 9 compatibility commands use lockfile mode
off without rewriting them.

The checked-in Bazel rc files keep local action results in ignored,
worktree-local disk caches, while setup-bazel continues to inject its
workflow-scoped cache paths in CI. CI's required qualified lane runs complete
root and consumer suites with `bazel test //...`; the only selectors are
semantic network, kernel-contract, and runfiles-manifest requirements. Bazel 9
uses the portable config to omit only networked tests already covered by Bazel
8. Tags do not encode a parallel CI test inventory.

Real mkosi image tests run in the qualified Linux lane. Unsupported or
privileged tests are either covered by the explicit kernel preflight or
modeled as execution requirements; they are not silently omitted.

## Action diagnostics

The image wrapper and serial boot lifecycle run the Bazel-built kernel
preflight before their expensive work. A failed probe preserves its individual
`FAIL <capability>` remediation lines and adds one
`KERNEL_CAPABILITY_FAILURE` boundary diagnostic. No action modifies a host
sysctl or privilege to make that probe pass.

All user-visible action failures use one of these stable categories, retain
the original tool output, and include a single `Action:` remediation:

| Category | Boundary |
| --- | --- |
| `KERNEL_CAPABILITY_FAILURE` | The proven namespace/mount preflight rejected the action. |
| `TOOLCHAIN_FAILURE` | A Bazel-provided executable or runfile could not start. |
| `NETWORK_FAILURE` | mkosi package acquisition failed with a network signal. |
| `ASSEMBLY_FAILURE` | mkosi exited for a non-network image-assembly reason. |
| `VM_FAILURE` | QEMU/firmware/guest lifecycle failed; its subtype and logs are retained. |

## Coverage

Bazel's coverage support instruments languages built by rules, not Starlark
executed during loading and analysis. Consequently, `bazel coverage` produces
an empty LCOV report for this repository's `.bzl` implementation. Analysis
test frameworks such as Bazel Skylib and `rules_testing` improve assertions but
do not provide Starlark line or branch coverage.

[`maxbirkner/coveragemap`](https://github.com/maxbirkner/coveragemap) consumes
LCOV and could visualize `.bzl` paths, but there is currently no meaningful
LCOV input to provide. Integration is deferred until either:

1. [Bazel Starlark coverage](https://github.com/bazelbuild/bazel/pull/15594)
   is available; or
2. the repository gains an instrumentable helper executable for which Bazel
   can produce LCOV.

Until then, behavioral coverage is enforced through analysis tests for every
public rule mode, executed tests of reviewable artifact projections, the
independent consumer module, and later OVMF/SeaBIOS boot tests. Adding an empty
coverage job or a zero-information visualization would create a misleading
quality signal.

## BCR publication

The `.bcr` directory contains templates for
[`bazel-contrib/publish-to-bcr`](https://github.com/bazel-contrib/publish-to-bcr).
A release requires:

1. A semantic version tag.
2. A stable release-asset source archive with a deterministic prefix.
3. Integrity metadata generated from that archive.
4. `metadata.json`, `source.json`, and a per-task Bazel version in
   `presubmit.yml`.
5. A test module in the extracted source archive.
6. A pull request to
   [`bazelbuild/bazel-central-registry`](https://github.com/bazelbuild/bazel-central-registry).

The recommended eventual automation is:

- [`bazel-contrib/.github` `release_ruleset`](https://github.com/bazel-contrib/.github)
  to create stable archives and build-provenance attestations.
- [`bazel-contrib/publish-to-bcr`](https://github.com/bazel-contrib/publish-to-bcr)
  to generate and open the BCR pull request.
- A draft GitHub release while attested assets are published, followed by
  finalization after the BCR publishing job.

The release workflow is intentionally not enabled in the hello-world phase.
It would require a `BCR_PUBLISH_TOKEN`, release-note policy, and immutable
archive preparation. Adding untested release automation now would create more
risk than readiness.

## Hermeticity boundary

The target is to provide through Bazel:

- mkosi source and Python runtime.
- Optional Python packages such as `pefile`.
- QEMU and firmware for boot tests.
- Image inspection and compression tools where redistributable.
- Package manifests and offline package repositories.

The Debian extension's `@mkosi_debian_snapshot//:repository` target is the
first offline repository input. Its repository rule performs only
content-addressed downloads of the locked `InRelease`, `Release`,
`Release.gpg`, and architecture-specific `Packages.xz` indexes. A declared
managed-Python action verifies both OpenPGP signatures with the pinned Debian
archive keyring, checks Release index hashes and package records, and stages
the exact `dists/` and `pool/` layout. This boundary is intentionally
separate from `mkosi_image`: it supplies stable provenance and inputs for a
future network-disabled mode without changing that rule's current package
acquisition or cache semantics.

Some requirements are properties of the execution platform rather than files:

- Linux kernel namespace support.
- `systemd-repart` and related systemd behavior.
- Filesystem and bootloader tooling.
- User-namespace policy and capabilities.

Until all required executables are toolchain inputs and image builds run
offline, release image actions must be treated as local or dedicated-runner
actions rather than generally hermetic remote-execution actions.

## References

- [Testing rules](https://bazel.build/rules/testing)
- [Bazel modules](https://bazel.build/external/module)
- [BCR contribution guide](https://github.com/bazelbuild/bazel-central-registry/blob/main/docs/README.md)
- [bazel-contrib rules template](https://github.com/bazel-contrib/rules-template)
- [bazel-contrib publishing workflow](https://github.com/bazel-contrib/publish-to-bcr)
- [Bazel Skylib](https://github.com/bazelbuild/bazel-skylib)
