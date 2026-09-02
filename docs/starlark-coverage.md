# Starlark coverage status

Coveragemap activation remains blocked. This page records reproducible evidence
and the reevaluation procedure; the
[behavior matrix](behavior-matrix.md) remains the release gate.

## Evidence recorded 2026-09-02

The supported Bazel releases were tested from an exact `main` checkout at
`04aa14cb0da843c6270a994e812c8231c7fbc62a`:

| Bazel | `bazel coverage` combined LCOV | Proposed flag |
| --- | --- | --- |
| 8.5.1 | 0 bytes; no `.bzl` source record | `Unrecognized option`, exit 2 |
| 9.2.0 | 0 bytes; no `.bzl` source record | `Unrecognized option`, exit 2 |

The probe loaded a temporary `.bzl` file defining a test rule. Its
implementation executed a true branch and left the false branch unexecuted.
For each version, the following representative commands ran:

```console
USE_BAZEL_VERSION=8.5.1 bazel coverage \
  --lockfile_mode=off --combined_report=lcov //issue26_probe:probe
USE_BAZEL_VERSION=8.5.1 bazel test --lockfile_mode=off \
  --starlark_coverage_report="$PWD/starlark.lcov" //issue26_probe:probe

USE_BAZEL_VERSION=9.2.0 bazel --ignore_all_rc_files coverage \
  --enable_bzlmod --lockfile_mode=off --combined_report=lcov \
  //issue26_probe:probe
USE_BAZEL_VERSION=9.2.0 bazel --ignore_all_rc_files test \
  --enable_bzlmod --lockfile_mode=off \
  --starlark_coverage_report="$PWD/starlark.lcov" //issue26_probe:probe
```

Both ordinary coverage runs reported `There was no coverage found.` Their
`bazel-out/_coverage/_coverage_report.dat` files had zero bytes. Neither
version accepted the proposed flag or created its requested report. The
temporary package and reports were removed after the probe.

[bazelbuild/bazel#15594](https://github.com/bazelbuild/bazel/pull/15594)
remains open at head `b603de0e6f400cfc5800d96507db68d3df646325`.
That head was last committed in June 2022, has no completed status checks, and
has not landed in either supported release. The latest upstream discussion
still identifies design, maintenance, and disabled-path performance concerns;
the pull request was most recently updated on 2026-07-03.

## Reevaluation

The existing weekly and manual CI triggers run
`ci/check-starlark-coverage-support.sh` for both pinned Bazel versions. The
check only inspects Bazel's help, so it does not duplicate the root or consumer
test suites. It fails when the proposed flag first appears, forcing a human to
repeat the branch-sensitive probe above before changing coverage CI.

Flag presence alone is not activation evidence. Coveragemap may be added only
after real LCOV contains `.bzl` source and line records that distinguish the
executed true branch from the unexecuted false branch. Any future coverage job
must reject a missing or empty report before invoking a pinned Coveragemap
revision. Synthetic LCOV, target-count proxies, and Starlark transpilation
remain prohibited.
