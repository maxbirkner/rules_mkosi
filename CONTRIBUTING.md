# Contributing

## Prerequisites

- Bazelisk, or the Bazel version declared in `.bazelversion`.
- [`prek`](https://prek.j178.dev/) 0.5 or newer.

The hello-world implementation and tests do not require mkosi or other host
image-building tools.

## Checks

Run all formatting, linting, spelling, secret, and repository hygiene checks:

```console
prek run --all-files
```

Run the ruleset tests and verify the committed lockfile:

```console
bazel test //...
bazel mod deps --lockfile_mode=error
```

Run the independent consumer test module:

```console
(
  cd e2e/smoke
  bazel test //...
)
```

The checked-in `.bazelrc` enables a worktree-local disk cache at
`.cache/bazel-disk`; the root and `e2e/smoke` modules have separate cache
directories. These paths are ignored by Git and Bazel, so they cannot become
source inputs or committed artifacts. The repository-only `.bazelrc.ci`
defines the `ordinary`, `manifest`, `qualified`, `qualified_manifest`,
`deterministic`, `kernel_preflight`, and `bazel9` configs used by CI. For
example, the ordinary compatibility commands are:

```console
bazel test --config=ordinary //...
USE_BAZEL_VERSION=9.2.0 bazel test --config=ordinary --config=bazel9 //...
```

Qualified image and boot coverage is intentionally opt-in:
`bazel test --config=qualified //...` from the root and
`bazel test --config=qualified //...` from `e2e/smoke`; the manifest-mode boot
pass uses `--config=qualified_manifest`. These configs select explicit
`ci_qualified`, `ci_manifest`, `ci_manifest_boot`, and
`requires_kernel_contract` tags rather than relying on `manual` expansion.
Networked image actions remain non-cacheable.

These commands use Bazel 8.5.1 and the two committed lockfiles by default:
the root `MODULE.bazel.lock` and `e2e/smoke/MODULE.bazel.lock`. CI also tests
pinned Bazel 9.2.0 with `--lockfile_mode=off` only for compatibility commands,
preserving those lockfiles rather than rewriting them. The module-resolution
fixtures intentionally run with `--lockfile_mode=off` on both supported
versions because they test extension semantics, not dependency locking. If
dependencies change, regenerate the two committed lockfiles with Bazel 8.5.1
using `--lockfile_mode=update`; never edit generated lockfiles by hand or
update them in CI.

The root command intentionally excludes `e2e/`. See
[the test architecture](docs/design/0003-ruleset-architecture.md#consumer-module)
and [`e2e/README.md`](e2e/README.md).

Install the same checks as Git hooks with `prek install`.

Commit messages should follow Conventional Commits. API changes require tests
at the analysis and consumer levels.

Releases follow Semantic Versioning. Release notes are generated from merged
pull requests, so pull request titles and descriptions must explain
user-visible behavior and compatibility changes.

## Review policy

All changes to `main` go through pull requests and must pass the
`CI conclusion` check. GitHub automatically requests Copilot code review.

Pull requests from contributors without write access require review by someone
with write access. Repository maintainers may use the pull-request-only
ruleset bypass for their own changes. GitHub cannot condition approval
requirements on the pull request author's permission, so the bypass is
technically available whenever a maintainer performs the merge. Maintainers
must not use it to merge an outside contribution they have not reviewed.
