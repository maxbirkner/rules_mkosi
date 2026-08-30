---
name: add-rule
description: Add or change a public rules_mkosi Starlark rule, provider, toolchain, or module extension with complete analysis, artifact, and consumer test coverage.
license: Apache-2.0
---

# Add or change a rules_mkosi rule

Use this workflow when implementing public Starlark behavior.

1. Read `docs/design/0003-ruleset-architecture.md` and the existing public API
   in `mkosi/defs.bzl`.
2. Search for an existing provider, toolchain field, helper, or test pattern
   before adding a new abstraction.
3. Implement rule logic in `mkosi/private/`. Re-export only intentional public
   symbols from `mkosi/defs.bzl`.
4. Model executable dependencies with execution-platform toolchains. Include
   executable runfiles and declare all action inputs and outputs.
5. Keep native mkosi configuration in configuration files when exposing it as
   Starlark would duplicate or constrain mkosi's API without adding safety.
6. Add analysis tests under `mkosi/tests` for providers, outputs, actions,
   arguments, failure modes, and toolchain selection.
7. Add an executed artifact test for observable output behavior.
8. Update `e2e/smoke` so an independent Bazelmod consumer exercises the public
   API and toolchain registration.
9. Update user and design documentation when the public API, compatibility, or
   hermeticity boundary changes.
10. Regenerate lockfiles only when module dependencies change.
11. Run the canonical validation commands from `CONTRIBUTING.md`. Run all
    supported Bazel majors for compatibility-sensitive changes.
12. Complete the `implementation-retrospective` skill before handoff. Keep
    non-blocking findings out of the feature PR and propose focused follow-up
    issues instead.

Do not weaken tests, disable sandboxing, enable network access, or mark an
action local merely to make it pass. If mkosi requires an exception, document
the precise platform limitation and scope the execution requirement to the
smallest possible action.
