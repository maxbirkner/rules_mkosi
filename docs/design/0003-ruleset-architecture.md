# Design: ruleset repository, testing, and release architecture

- **Status:** Accepted
- **Date:** 2026-08-29

## Goals

The repository must:

- Be a Bazelmod-native ruleset suitable for BCR publication.
- Keep the public API small and separate from implementation details.
- Test providers and actions during analysis, and generated artifacts during execution.
- Include an independent consumer module using `local_path_override`.
- Keep portable analysis coverage separate from tests that need a qualified Linux runner.
- Move toward Bazel-provided toolchains and offline image inputs.

## Module policy

`MODULE.bazel` leaves `version` unset: the BCR publishing workflow patches it into the registry copy, and a source version causes problems for consumers using non-registry overrides.
`compatibility_level` is omitted because it is a deprecated no-op in Bazel 8 and 9; breaking releases provide migration diagnostics and documentation instead.

The baseline is the lowest Bazel version in `ci/bazel_versions.json`, with a rolling policy of supporting the current and previous LTS majors (currently 8 and 9).
`.bazelversion` pins the version that generates the lockfiles.

## Public API boundary

Consumers load rules and providers only from `//mkosi:defs.bzl`; `//mkosi/private` is implementation.
Toolchain types are public because registration and advanced integrations need stable labels.

- **Typed outputs.**
  `mkosi_image` returns `MkosiImageInfo`, whose artifact fields are each a `File` or `None`.
  Consumers select fields rather than infer roles from file names or `DefaultInfo` order, so new outputs never change existing meanings.
- **Explicit build modes.**
  `tracer` is never cached, so it makes no hermeticity claim; it installs packages from the network, or offline from a `debian_snapshot`.
  `release` takes packages only from an authenticated `DebianSnapshotInfo`, blocks the network, and may be cached.
  Release mode rejects any configuration that could read undeclared host state or reintroduce a network package source, so a cache hit is always valid.
- **Typed inputs.**
  Configuration and source directories, and image payloads, are marked with typed rules so their roles and executable bits are explicit; Bazel does not preserve source mode bits.
- **Replaceable Python, fixed bootstrap.**
  mkosi runs on a Bazel-managed Python 3.14 resolved through rules_python, which a root module may replace with another in-build 3.14 runtime.
  The Debian tools launcher instead uses a pinned static interpreter and static native bootstrap, because it must start before any dynamic loader is trusted.
- **QEMU and firmware** are a separate toolchain used only by tests.

## Test layers

| Layer | Purpose |
| --- | --- |
| Analysis tests | `analysistest` checks providers, absent artifacts, toolchain selection, and registered actions without executing them. Preferred for rule logic. |
| Artifact tests | Validate generated images through reviewable projections (GPT, metadata, verity, UKI sections, reproducibility manifests) rather than checked-in or byte-compared images. |
| Consumer module | `e2e/smoke` resolves rules_mkosi independently, exercising public labels, extensions, toolchain registration, and a consumer-registered Python runtime. |
| Boot tests | Boot images under QEMU with OVMF or SeaBIOS through one firmware-neutral serial and QMP lifecycle, including multi-boot A/B update and rollback. |
| Module resolution | Nested-module fixtures check extension selection and error messages. |

A nested `MODULE.bazel` does not stop root `//...` traversal, so `.bazelignore` excludes `e2e/`.
The consumer stays in release archives because BCR runs it as the test module.

Reproducibility is proved by building release images in two clean output roots with all caches disabled, confirming that each image action really executed, and comparing normalized manifests.
The canonical image digest ignores only GPT disk and partition GUIDs and the checksums derived from them.
Build-process state such as paths, timestamps, and ownership is outside the manifest.
Externally signed artifacts are not claimed to be reproducible.

Inspection tools, QEMU, and firmware are resolved as Bazel toolchains, never assumed on the runner.

Remaining test work: power interruption tests outside ordinary BCR workers, and representative physical-hardware qualification.

## CI

GitHub Actions runs the root and consumer suites on the pinned Bazel versions in `ci/bazel_versions.json`, plus a weekly run that detects breakage from rolling releases.
Bazel 8 validates the committed lockfiles strictly; Bazel 9 uses lockfile mode off and never rewrites them.
Actions are pinned by commit SHA, permissions default to read-only, superseded branch builds are cancelled, and one conclusion job gates branch protection.

CI runs `bazel test //...` with execution-policy configs rather than a hand-maintained test list.
Tags are semantic (`requires-network`, `requires_kernel_contract`, `manifest`), and tests that need the host kernel run after an explicit preflight instead of being skipped.

## Action diagnostics

Image actions and boot tests run the kernel preflight before expensive work, and never modify host sysctls or privileges to make it pass.
Every user-visible failure keeps the original tool output and adds one category and one `Action:` remediation:

| Category | Boundary |
| --- | --- |
| `KERNEL_CAPABILITY_FAILURE` | The namespace and mount preflight rejected the host. |
| `TOOLCHAIN_FAILURE` | A Bazel-provided executable or runfile could not start. |
| `NETWORK_FAILURE` | mkosi package acquisition failed with a network signal. |
| `ASSEMBLY_FAILURE` | mkosi failed for another reason. |
| `VM_FAILURE` | QEMU, firmware, or the guest failed; the subtype and logs are retained. |

## Coverage

Bazel does not instrument Starlark, so `bazel coverage` yields empty LCOV for `.bzl` files, and analysis-test frameworks improve assertions but not line coverage.
[`maxbirkner/coveragemap`](https://github.com/maxbirkner/coveragemap) integration is deferred until [Bazel Starlark coverage](https://github.com/bazelbuild/bazel/pull/15594) is available or logic moves into an instrumentable helper.
An empty coverage job would be a misleading quality signal.
Behavioral coverage is tracked in the [behavior catalog](../behavior-matrix.md); see [Starlark coverage status](../starlark-coverage.md) for the evidence and reevaluation procedure.

## BCR publication

The `.bcr` directory contains templates for [`bazel-contrib/publish-to-bcr`](https://github.com/bazel-contrib/publish-to-bcr).
A release requires:

1. A semantic version tag.
2. A stable release-asset source archive with a deterministic prefix.
3. Integrity metadata generated from that archive.
4. `metadata.json`, `source.json`, and a per-task Bazel version in `presubmit.yml`.
5. A test module in the extracted source archive.
6. A pull request to [`bazelbuild/bazel-central-registry`](https://github.com/bazelbuild/bazel-central-registry).

A `v*.*.*` tag runs `.github/workflows/release.yml`: [`bazel-contrib/.github` `release_ruleset`](https://github.com/bazel-contrib/.github) builds and attests the archive with `release_prep.sh`, `publish-to-bcr` opens the registry pull request, and the draft GitHub release is published afterwards.
Release notes are generated from pull request titles.
The [`.bcr` README](../../.bcr/README.md) lists the maintainer setup and release steps.

BCR runners cannot be assumed to provide user namespaces, a group-free Bazel server, or access to snapshot.debian.org, so the presubmit runs only the consumer tests that need none of them.
Image builds and boot tests stay in this repository's CI.

## Hermeticity boundary

Provided through Bazel:

- mkosi and its Python runtime and packages.
- The Debian 13 build-time userspace, as a checksum-pinned, authenticated archive.
- Authenticated Debian snapshot repositories, built-in or consumer-locked, as the only package source of release images.
- QEMU and firmware for boot tests.

Properties of the execution platform rather than files:

- Linux namespace and mount support and user-namespace policy, checked by the [host-kernel contract](0004-host-kernel-contract.md).

Because of that platform dependency, image actions are local or dedicated-runner actions and are not offered for remote execution.

## References

- [Testing rules](https://bazel.build/rules/testing)
- [Bazel modules](https://bazel.build/external/module)
- [BCR contribution guide](https://github.com/bazelbuild/bazel-central-registry/blob/main/docs/README.md)
- [bazel-contrib rules template](https://github.com/bazel-contrib/rules-template)
- [bazel-contrib publishing workflow](https://github.com/bazel-contrib/publish-to-bcr)
- [Bazel Skylib](https://github.com/bazelbuild/bazel-skylib)
