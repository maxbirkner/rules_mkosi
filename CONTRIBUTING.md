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
