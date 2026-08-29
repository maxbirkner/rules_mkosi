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
- Avoid requiring mkosi or image tooling for the initial test suite.
- Evolve toward Bazel-provided toolchains and offline image inputs.

## Module policy

`MODULE.bazel` intentionally leaves `version` unset. The BCR publishing
workflow patches the release version into the registry copy. Setting a source
version causes problems for consumers using non-registry overrides.

`compatibility_level` is also omitted. It became a deprecated no-op in recent
Bazel 8 and 9 releases. Breaking releases must instead provide explicit
migration diagnostics and documentation.

The initial compatibility range is Bazel 7 and newer. CI exercises the latest
resolvable releases from Bazel 7, 8, and 9. `.bazelversion` pins the development
version.

## Public API boundary

Consumers load rules and providers only from `//mkosi:defs.bzl`. Files below
`//mkosi/private` are implementation details. The toolchain type is public
because registration and advanced integrations need a stable label.

The initial `mkosi_image` action writes a deterministic fixture without
executing a host binary. This is deliberate: it proves rule analysis,
toolchain resolution, providers, outputs, and consumer usage without claiming
that mkosi or its host utilities are already hermetic.

The toolchain provider currently carries only a logical name and output
contract version. It will later carry:

- The pinned mkosi executable and runfiles.
- A Python runtime supplied by Bazel.
- Explicit executable dependencies.
- A declared host-capability manifest for dependencies that cannot yet be
  distributed through Bazel.

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

A `diff_test` compares the built placeholder image with a checked-in golden
file. Future artifact tests will inspect:

- mkosi's effective configuration.
- Partition tables and GPT type UUIDs.
- Filesystem and verity metadata.
- UKI sections and signatures.
- Reproducibility across repeated builds.

Inspection binaries must be supplied through Bazel toolchains rather than
assumed to exist on the runner.

### Consumer module

`e2e/smoke` is an independent Bazel module. It depends on `rules_mkosi` through
`local_path_override`, registers the public module extension and toolchain,
builds an image, and runs build and content tests.

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

GitHub Actions runs the root and consumer suites against Bazel 7, 8, and 9.
Actions are pinned by commit SHA, permissions default to read-only, and
concurrent superseded branch builds are cancelled. A stable conclusion job can
be used for branch protection.

The weekly scheduled run detects breakage from rolling Bazel releases and
external dependency changes. The committed lockfile is validated separately
with the development Bazel version.

Real mkosi image tests will use a dedicated Linux job. Unsupported or
privileged tests must not be mixed with portable analysis tests or the BCR
smoke module.

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
