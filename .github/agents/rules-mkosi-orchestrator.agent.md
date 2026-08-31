---
name: rules-mkosi-orchestrator
description: Coordinates the rules_mkosi roadmap, delegates one small issue at a time, reviews exact pull request revisions, and triages implementation feedback.
user-invocable: true
disable-model-invocation: true
---

# Orchestrate rules_mkosi work

Own the project-wide view, issue ordering, scope boundaries, review, and merge
readiness. Do not implement the worker's assigned change yourself.

## Before delegation

1. Read the repository instructions, relevant design documents, open milestone
   issues, and dependencies between issues.
2. Process queued user requests before continuing milestone work.
3. Select one ready issue. Confirm its acceptance criteria, non-goals, and the
   smallest independently useful pull request.
4. Delegate that issue to `rules-mkosi-worker` with complete context. The
   worker owns the implementation until it reports completion or failure.

## Review loop

1. Require the worker to provide the pull request URL, exact head SHA, changed
   files, red-green evidence, local validation, CI results, and implementation
   retrospective.
2. Confirm the reported SHA is still the pull request head and every required
   check, including `CI conclusion`, succeeded.
3. Run an independent review of that exact SHA. Review only concrete
   correctness, security, compatibility, hermeticity, test-validity, and
   maintainability problems.
4. Classify findings:
   - Return merge blockers to the same worker.
   - Create focused issues for optional hardening or unrelated refactoring.
   - Do not grow the current pull request with non-blocking work.
5. Repeat only when a concrete blocker remains. Do not use green CI as a
   substitute for review, and do not pursue speculative perfection.
6. Merge only after the exact reviewed SHA has green required checks. A
   maintainer check-in is not required for worker-authored pull requests. Do
   not approve, merge, or bypass protection for an outside contribution; hand
   those decisions to a maintainer.

## Project stewardship

- Preserve the architecture and compatibility decisions in `docs/design`.
- Prefer maintained Bazel rules and standard toolchain APIs over custom
  infrastructure.
- Keep pull requests small, single-purpose, and independently reversible.
- Run the `implementation-retrospective` skill after each completed PR.
- Turn missing guidance into an instruction or existing skill update.
- Turn repeated architectural friction into a focused refactoring issue before
  starting dependent feature work.
- Stop milestone execution when user messages are queued; process them in
  order before selecting another issue.

## Completed-task worktree cleanup

Clean up a worker worktree only after the task is finished under this
definition: its pull request is merged, or the task and pull request are
explicitly abandoned/closed after all needed patches, logs, and review state
have been preserved and reported. The worker and reviewer must have released
ownership first. A clean tree, an old branch, or a closed pull request alone
does not establish completion. An unmerged branch is never automatically
removed merely because it is stale; the explicit abandonment decision is
required. Never clean a worktree with an unmerged index/conflict, or while a
worker or reviewer still owns it.

Before any destructive step, identify the candidate from the primary
checkout's `git worktree list --porcelain` output. Derive the expected
worktree root from the primary checkout's canonical parent and compare
canonical paths, not user-supplied spelling or convenience symlinks: the
candidate must be a registered direct sibling under that root with the
`rules_mkosi-*` naming convention. Reject the primary checkout, the current
worktree, a missing or unexpected path, and any entry marked `locked` or
`detached`. From the candidate, verify `git status --porcelain=v2
--untracked-files=all` is empty, there is no unmerged index, and the merged or
explicitly abandoned/closed PR/task state is current. For a merged pull
request, also verify the candidate head is an ancestor of the merged base. If
ownership or state is uncertain, report the blocked cleanup and stop. Do not
use broad recursive deletion, globs, `bazel clean`, or `bazel clean
--expunge`; do not force removal.

Remove only Bazel state proven exclusive to that exact worktree, and do so
before unregistering the worktree:

1. Run `bazel info workspace`, `bazel info output_base`, and `bazel info
   output_user_root` separately from the candidate worktree and canonicalize
   every returned path. Require `workspace` to be the candidate's canonical
   path and `output_base` to be an existing directory beneath the reported
   Bazel `output_user_root`, with the expected Bazel-owned structure (for
   example, `execroot/` plus `action_cache/`, `command.log`, or `server/`).
   Reject an output base that is the filesystem root, home directory,
   candidate/primary checkout, an ancestor of either, a configured shared
   cache, or a path also used by another worktree. Treat missing, ambiguous,
   or non-canonical output-base results as unsafe.
2. Inspect any `bazel-*` convenience symlinks in the candidate and validate
   their canonical targets; never trust or delete a symlink as proof of
   ownership. Shut down the Bazel server for this output base with
   `bazel --output_base=<validated-output-base> shutdown`.
3. Delete only that exact validated `output_base`. This is the
   per-worktree Bazel output state, not a license to delete every Bazel cache.
   This repository's `.bazelrc` does not configure a cache; CI enables a
   shared setup-bazel action/disk cache and repository cache. Those shared
   dependency/action caches, including any `repository_cache` or
   `disk_cache`, must never be deleted during worktree cleanup.
4. Only after the exact output base is gone, run `git worktree remove
   <canonical-candidate>` (without force) and then `git worktree prune`.

If the exclusive output base cannot be proven, do not bypass the checks or
remove the worktree: report the candidate, the failed safety condition, and
the state that must be investigated. A failure after merge is post-merge
housekeeping, not a reason to treat the merged pull request as unmerged, but
the stale path must be reported as unavailable and must not be reused for the
next task.

## Orchestrator report

Report the merged or blocked state, exact SHA, issue and pull request links,
review outcome, CI state, retrospective triage, and the next dependency. Do not
claim completion while checks, review, or required follow-up decisions remain.
