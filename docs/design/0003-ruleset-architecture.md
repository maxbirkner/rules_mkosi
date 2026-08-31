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

`mkosi_image` exposes only its generated raw image through `MkosiImageInfo`.
The action invokes the pinned mkosi v27 executable and the pinned Debian 13
tools tree through registered toolchains. Its target package acquisition is
networked and its Linux namespace/mount requirements are execution-platform
properties, so it is explicitly non-cacheable and not a remote- or
offline-hermetic action. The tracer action forces disk/raw/uncompressed output
and disables split artifacts; configuration files cannot redirect the declared
artifact or select a custom format. The configuration label is mandatory and
must resolve to one file; Bazel rejects multi-file config targets during
analysis.

The toolchain provider carries the pinned mkosi executable and complete
runfiles, a Bazel-managed Python runtime, the optional `pefile` dependency
needed by mkosi's bootable PE inspection paths, and source provenance
(immutable URL and SHA-256 integrity). QEMU and firmware remain outside this
image-building action and are supplied by their separate toolchain.

## Test layers

### Analysis tests

`bazel_skylib` `analysistest` inspects the configured target without executing
the action. It verifies:

- `MkosiImageInfo` is present.
- Provider fields are correct.
- The output name is stable.
- Toolchain resolution selected the expected toolchain.
- Exactly one expected action was registered.

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
consumes a minimal configuration through the public `mkosi_image` rule, and
has a manually selected artifact test for the real image.

A nested `MODULE.bazel` does not stop root `//...` traversal. `.bazelignore`
therefore excludes `e2e/`, and CI invokes the consumer from its own working
directory. The consumer must remain in release archives because BCR runs it as
the module's test project.

### Future boot tests

The production test hierarchy will add:

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

Real mkosi image tests will use a dedicated Linux job. Unsupported or
privileged tests must not be mixed with portable analysis tests or the BCR
smoke module.

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
