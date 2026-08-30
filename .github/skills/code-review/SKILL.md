---
name: code-review
description: Review rules_mkosi changes for Bazel API compatibility, hermeticity, toolchain correctness, test coverage, CI integrity, and BCR compatibility.
license: Apache-2.0
---

# Review rules_mkosi changes

Report only concrete correctness, compatibility, security, or maintainability
problems. Check:

1. **Public API:** consumers load only `mkosi/defs.bzl`; private symbols and
   labels have not become accidental contracts.
2. **Bazel compatibility:** Starlark and module APIs work on Bazel 7, 8, and 9,
   or newer usage has a tested guard.
3. **Toolchains:** executables use the execution configuration, complete
   runfiles are inputs, and platform constraints describe where the tool can
   actually run.
4. **Hermeticity:** no undeclared host binaries, ambient environment variables,
   mutable repositories, untracked caches, or hidden network access.
5. **Execution exceptions:** `local`, `no-remote`, `no-sandbox`, privileges,
   and network requirements are justified and scoped narrowly.
6. **Determinism:** downloads have stable URLs and integrity hashes; package
   inputs and timestamps are pinned; output names and providers are stable.
7. **Tests:** behavior is covered by analysis tests, executed artifact tests,
   and the independent `e2e/smoke` module where it affects consumers.
8. **Lockfiles:** generated lockfiles changed only when module resolution
   changed and were not edited manually.
9. **CI:** action references remain full commit SHAs, permissions remain
   least-privilege, and the `CI conclusion` gate cannot pass after a required
   job fails or is cancelled.
10. **BCR:** the smoke module remains in release archives, runtime dependencies
    are not accidentally marked dev-only, and source archives remain stable.

Separate merge blockers from follow-up hardening. A review finding blocks the
current PR when it violates an explicit repository requirement, breaks the
stated behavior, makes a supported configuration fail, creates an immediate
security problem in the documented threat model, or contradicts the public
API. Record optional hardening and unrelated refactoring as focused follow-up
issues.

After review, use the `implementation-retrospective` skill to capture recurring
review findings as either missing guidance or architectural friction.

For real disk-image changes, additionally require evidence for partition
layout, OVMF and SeaBIOS boot paths, offline builds, update rollback, and
failure behavior. Do not accept a successful image build alone as evidence
that the image is bootable or safely updateable.
