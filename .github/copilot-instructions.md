# Repository instructions

`rules_mkosi` is a Bazelmod-native Starlark ruleset for assembling bootable
Linux images with mkosi.

- Preserve compatibility with Bazel 7, 8, and 9. Do not use newer Bazel APIs
  without a tested compatibility guard.
- Do not add `WORKSPACE` support. `local_path_override` belongs only in
  independent test modules such as `e2e/smoke`.
- Consumers load rules and providers from `//mkosi:defs.bzl`. Keep
  implementation details under `//mkosi/private`; tests, examples, and
  consumers must not load private files.
- Resolve tools through registered toolchains. Production rules must not
  discover or invoke undeclared host executables.
- Do not claim an image action is hermetic when it needs network access,
  privileges, mutable package-manager state, host capabilities, or undeclared
  tools. Model inputs where possible and declare execution requirements where
  isolation is impossible.
- Keep release builds deterministic and offline-capable. Pin downloaded tools
  and packages by integrity hash; never silently fall back to a host tool or a
  mutable package repository.
- Every rule behavior change needs an analysis test under `mkosi/tests`.
  Executed output behavior also needs an artifact test and coverage in the
  independent `e2e/smoke` consumer module.
- `MODULE.bazel.lock` files are generated, committed artifacts. Regenerate
  them deliberately with the pinned Bazel version; never edit them manually.
- Keep GitHub Actions permissions minimal and pin third-party actions to full
  commit SHAs with a version comment.
- Use `prek` as the only formatting and linting entry point. Do not duplicate
  individual formatter commands in documentation or CI.
- Follow the canonical validation commands and nested-module rationale in
  `CONTRIBUTING.md`.
- Keep pull requests small and single-purpose. Do not expand a feature PR with
  non-blocking hardening; record that work as focused follow-up issues.
- Every implementation handoff must include an implementation retrospective:
  documentation gaps, confusing APIs or architecture, repeated failures, and
  deferred work. Write `None` for empty categories rather than omitting them.
- Before starting the next feature, triage retrospective findings. Fix missing
  guidance in the relevant instruction or skill, and schedule a focused
  refactoring when repeated friction indicates a code smell.

When compatibility-sensitive Starlark changes are made, repeat the root and
consumer suites with `USE_BAZEL_VERSION=7.7.1`.
