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
explicitly abandoned/closed PR/task state is current. For a merged pull request, run `git fetch origin main` and query the fresh
authoritative PR record, not a cached handoff. Require state `MERGED`, the
candidate branch ref and worktree `HEAD` to match the reviewed PR head SHA, and
the PR-recorded merge commit to be reachable from the fetched `origin/main`.
Check head ancestry only for merge methods that preserve head identity; do not
require it after a squash merge. For an abandoned/closed task, require
separate explicit lifecycle evidence, preserve and report the exact head and
needed patches/logs/review state, and prove that no unmerged work remains to
preserve. If ownership or state is uncertain, report the blocked cleanup and
stop. Do not use broad recursive deletion, globs, `bazel clean`, or `bazel
clean --expunge`; do not force removal.

Remove only Bazel state proven exclusive to that exact worktree, and do so
before unregistering it. Account for every Bazel workspace the task actually
exercised, at minimum the root and independent `e2e/smoke` workspaces, plus
each module-resolution fixture or other workspace named in the worker's
commands and handoff. If complete workspace accounting cannot be established,
report blocked cleanup.

1. Automatic deletion is allowed only for Bazel's uncustomized default output
   base. For each exercised workspace, query the no-RC default read-only:
   `bazel --ignore_all_rc_files info output_base` on Bazel 8, or
   `bazel --ignore_all_rc_files info --lockfile_mode=off output_base` on Bazel
   9. Canonicalize that result. Compare the worker's recorded output base with
   the default path exactly, including its parent and the lowercase MD5 of the
   workspace's canonical path as its 32-hex-digit leaf. Verify that MD5 rule
   against both supported Bazel versions before relying on it. Require
   non-symlink Bazel markers such as `DO_NOT_BUILD_HERE`, `execroot/`, and
   `command.log` as corroboration, never as authorization. Any explicit or
   custom `--output_base`, `--output_user_root`, arbitrary root, marker-only
   directory, or unknown provenance blocks cleanup.
2. Use the worker handoff's exact commands, workspaces, and environment to
   account for startup options (before the command), command options, and
   every `.bazelrc.user`, home, and system RC source. Re-run each actual
   command/config read-only with its `--announce_rc` command option where
   feasible; treat that report as evidence, not a complete effective-config
   resolver. If any setting that can configure `output_base`,
   `output_user_root`, `disk_cache`, or `repository_cache` is not fully
   accounted for, report blocked cleanup. This repository's root `.bazelrc`
   configures the exact workspace-local disk cache
   `<workspace>/.cache/bazel-disk`; the independent `e2e/smoke` workspace
   configures its own `<workspace>/.cache/bazel-disk`. These are disk-cache
   directories, not Bazel `output_base` directories. For every exercised
   workspace, resolve that exact expected path and prove that it is a
   non-symlink directory owned by the candidate workspace, ignored by Git,
   contained by that workspace, and non-overlapping with every other cache,
   registered worktree, and output base. A cache missing after a clean run is
   still accounted for only when the rc source and exact expected path are
   proven. Remove each accounted workspace-local cache at its exact canonical
   path before `git worktree remove`; if any configured cache cannot be
   accounted for, report blocked cleanup. Shared setup-bazel
   disk/repository caches may remain only when their canonical paths are
   proven outside and non-overlapping every worktree and output base; never
   delete those shared caches.
3. Protect every registered worktree and every output base discovered for
   another workspace. Reject any overlap, including an output base or
   workspace-local disk cache equal to or containing a worktree, another
   output base, or another cache, or being contained by one. Validate
   `bazel-*` convenience-symlink targets; never trust a symlink as ownership
   proof. Shut down each corresponding Bazel server with its exact validated
   default output base, then delete only those exact output bases. The
   repository rc files own the root and e2e workspace-local caches described
   above, while CI's setup-bazel separately manages shared disk and repository
   caches; the latter must remain protected.
4. Only after all validated output bases are gone, run `git worktree remove
   <canonical-candidate>` without force. This already unregisters that exact
   worktree. Before any repository-wide prune, run `git worktree prune
   --dry-run --verbose`; run the real prune only when the dry run reports no
   unrelated entry (at most the just-removed candidate). Otherwise skip/block
   prune so cleanup cannot unregister another missing worktree.

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
