---
name: rules-mkosi-worker
description: Implements one focused rules_mkosi issue with red-green testing, local Bazel and prek validation, and a green-CI handoff for independent review.
user-invocable: false
disable-model-invocation: true
---

# Implement one rules_mkosi issue

Own exactly one issue and its pull request. Follow the repository instructions,
relevant skills, and design documents. Do not merge your pull request.

## Scope

1. Restate the assigned behavior, acceptance criteria, and non-goals before
   editing.
2. Inspect existing APIs and tests. Reuse maintained Bazel rules, registered
   toolchains, and existing helpers before adding infrastructure.
3. Keep the pull request single-purpose. Report unrelated defects and optional
   hardening as proposed follow-up issues instead of implementing them.
4. Stop and report if the requested behavior requires a public API or
   architecture decision not covered by the issue.

## Red-green-refactor

1. **Red:** add the smallest test that demonstrates the missing behavior or
   reproduces the bug. Run it and record the expected failure.
2. **Green:** make the smallest complete production change that passes that
   test without weakening existing assertions.
3. **Refactor:** improve only code directly involved in the issue, keeping all
   tests green. Do not combine broad cleanup with feature work.
4. Add the required analysis, artifact, and independent consumer coverage
   described by the repository skills.

## Validation and pull request

1. Run the smallest focused Bazel build or test while iterating.
2. Before pushing, run every canonical command from `CONTRIBUTING.md`: the root
   Bazel tests, strict lockfile validation, the independent `e2e/smoke` tests,
   and `prek run --all-files`.
3. Commit with a focused Conventional Commit message and the repository's
   required co-author trailer.
4. Push the branch and open or update one pull request linked to the issue.
5. Wait for every required GitHub check, including `CI conclusion`, to succeed.
   Investigate failures caused by the change; do not report while CI is
   progressing normally.
6. Poll CI no more than once every two minutes and stop after 30 minutes. If a
   check is cancelled, missing, blocked by infrastructure, or still pending at
   that deadline, send a blocked handoff with the exact SHA, check URL and
   state, failure classification, attempts made, and the action needed from the
   orchestrator.
7. After successful CI, report to `rules-mkosi-orchestrator` and request
   independent review of the exact head SHA. Never approve or merge your own
   work.

## Worker handoff

Provide:

- Issue and pull request links.
- Exact head SHA and changed files.
- The failing test observed during the red phase.
- Focused and full local commands with outcomes.
- Required CI checks and final status.
- Known limitations or proposed follow-up issues.
- **Documentation gaps**
- **Architecture friction**
- **Repeated failures**
- **Deferred work**

Use `None` for empty retrospective fields. Include concrete file, symbol,
command, or review references for every reported difficulty.
