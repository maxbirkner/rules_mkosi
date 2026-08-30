---
name: implementation-retrospective
description: Turn implementation friction and review feedback into focused documentation, refactoring, or follow-up work before starting another feature.
license: Apache-2.0
---

# Run an implementation retrospective

Use this workflow after an implementation PR reaches handoff or merge.

1. Ask every implementor to report these fields:
   - **Documentation gaps:** guidance that was missing, ambiguous, or stale.
   - **Architecture friction:** APIs, boundaries, or ownership that made a
     focused change unexpectedly difficult.
   - **Repeated failures:** failed approaches and the underlying reason.
   - **Deferred work:** non-blocking correctness, hardening, or portability
     work intentionally kept out of the PR.
2. Require concrete references such as files, symbols, commands, or review
   findings. Use `None` when a field has no findings.
3. Classify each finding before starting the next feature:
   - Update an existing instruction or skill when a stable convention was
     difficult to discover.
   - Add a narrowly scoped skill only when the workflow is reusable and cannot
     be expressed clearly in an existing skill.
   - Create a focused refactoring issue when multiple failures trace to the
     same abstraction, duplicated logic, or unclear ownership.
   - Create a focused follow-up issue for non-blocking hardening or portability.
4. Do not fold unrelated retrospective work back into the completed feature
   PR. Prefer one documentation or refactoring concern per subsequent PR.
5. Record why no action is needed when feedback is situational rather than a
   reusable lesson.

The handoff is incomplete until the findings are triaged into updated guidance,
an issue, or an explicit no-action decision.
