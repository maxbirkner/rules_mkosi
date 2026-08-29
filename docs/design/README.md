# Design evaluations

These documents capture the research and architectural decisions that precede
the implementation of `rules_mkosi`.

| Document | Scope |
| --- | --- |
| [0001 - Bazel OS image tooling](0001-bazel-os-image-tooling.md) | Existing Bazel integrations, Constellation, and whether a new ruleset is justified |
| [0002 - OS build foundation](0002-os-build-foundation.md) | mkosi versus distribution and appliance build systems |
| [0003 - Ruleset architecture](0003-ruleset-architecture.md) | Repository layout, test and coverage strategy, hermeticity boundary, CI, and BCR publishing |
| [0004 - Host-kernel contract](0004-host-kernel-contract.md) | Preflight checks and the execution-platform decision for unprivileged mkosi actions |

The evaluations reflect the ecosystem as researched on 2026-08-29. Versions,
project status, and external capabilities must be rechecked before relying on
them for a release decision.
