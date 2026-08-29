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
at the analysis and consumer levels.
