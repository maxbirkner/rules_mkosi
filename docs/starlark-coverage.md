# Starlark coverage status

Line coverage for `.bzl` files is not available, so the [behavior catalog](behavior-matrix.md) remains the coverage contract.

## Evidence (2026-09-02)

A probe test rule whose implementation executes one branch and skips another was run under `bazel coverage --combined_report=lcov`:

| Bazel | Combined LCOV | `--starlark_coverage_report` |
| --- | --- | --- |
| 8.5.1 | Empty; no `.bzl` record | Unrecognized option |
| 9.2.0 | Empty; no `.bzl` record | Unrecognized option |

Starlark coverage is proposed upstream in [bazelbuild/bazel#15594](https://github.com/bazelbuild/bazel/pull/15594), which has not landed in either supported release.

## Reevaluation

The monthly `Starlark coverage capability` workflow runs `ci/check-starlark-coverage-support.sh` for both pinned Bazel versions.
Run it locally with:

```console
USE_BAZEL_VERSION=8.5.1 ./ci/check-starlark-coverage-support.sh
USE_BAZEL_VERSION=9.2.0 ./ci/check-starlark-coverage-support.sh
```

The script runs the probe in an isolated, temporary module and removes it afterwards.
It succeeds while coverage is unavailable and fails once a report contains both an executed and an unexecuted line of the probe's `.bzl` file, which is the signal to add coverage reporting.
A coverage job may only be added on top of such real LCOV; empty or synthetic reports and target counts are not accepted as coverage.
