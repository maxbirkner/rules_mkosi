# Contributing

## Prerequisites

- Bazelisk, or the Bazel version declared in `.bazelversion`.
- Buildifier for formatting Starlark and Bazel files.

The hello-world implementation and tests do not require mkosi or other host
image-building tools.

## Checks

Run the ruleset tests from the repository root:

```console
bazel test //...
```

Run the independent consumer module:

```console
cd e2e/smoke
bazel test //...
```

Check formatting:

```console
buildifier -mode=check -lint=warn \
  MODULE.bazel BUILD.bazel \
  mkosi/*.bzl mkosi/*/BUILD.bazel mkosi/*/*.bzl
```
Commit messages should follow Conventional Commits. API changes require tests
at the analysis and consumer levels.

## Review policy

All changes to `main` go through pull requests and must pass the
`CI conclusion` check. GitHub automatically requests Copilot code review.

Pull requests from contributors without write access require review by someone
with write access. Repository maintainers may use the pull-request-only
ruleset bypass for their own changes. GitHub cannot condition approval
requirements on the pull request author's permission, so the bypass is
technically available whenever a maintainer performs the merge. Maintainers
must not use it to merge an outside contribution they have not reviewed.
at the analysis and consumer levels.
