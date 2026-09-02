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
For each version, `ci/check-starlark-coverage-support.sh` creates a
permission-private, unique probe directory containing its module, reports, and
`output_user_root`. The directory is adjacent to, not inside, the checkout so
Bazel never treats its private caches as source content. Every Bazel invocation
uses `--ignore_all_rc_files` and that output root. The script runs the
equivalent of:

```console
USE_BAZEL_VERSION=8.5.1 ./ci/check-starlark-coverage-support.sh
(cd issue26_starlark_coverage_probe && \
  USE_BAZEL_VERSION=8.5.1 bazel --ignore_all_rc_files \
    --output_user_root=/fresh/probe/output-user-root coverage \
    --lockfile_mode=off --combined_report=lcov //:probe)

USE_BAZEL_VERSION=9.2.0 ./ci/check-starlark-coverage-support.sh
(cd issue26_starlark_coverage_probe && \
  USE_BAZEL_VERSION=9.2.0 bazel --ignore_all_rc_files \
    --output_user_root=/fresh/probe/output-user-root coverage \
    --lockfile_mode=off --combined_report=lcov //:probe)
```

When isolated `bazel help` advertises `--starlark_coverage_report`, the script
deletes and recreates the private reports directory, runs the same `//:probe`
target with that flag, and inspects the report only after that invocation
succeeds and freshly creates it. An advertised flag that fails or creates no
report is itself an actionable failure. The script also verifies that the
isolated Bazel version equals `USE_BAZEL_VERSION`. Cleanup shuts down the
private Bazel server and removes the entire probe directory.

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

The dedicated `Starlark coverage capability` workflow runs monthly and on
manual dispatch for both pinned Bazel versions. It checks out the repository,
sets up Bazel, and runs only `ci/check-starlark-coverage-support.sh`; it does
not run or alter the root, manifest, or consumer qualification suites in the
`CI` workflow.

The script runs one generated Starlark test rule under `bazel coverage`, tries
the proposed flag when Bazel advertises it, and removes its package and report.
Continued missing, empty, or non-Starlark LCOV succeeds with an explicit job
summary. A report counts as meaningful only when the probe's `.bzl` source has
both a positive `DA` execution count and a zero `DA` count. That result fails
the job loudly with an instruction to resume issue #26.

Flag presence alone is not activation evidence. Coveragemap may be added only
after real LCOV contains `.bzl` source and line records that distinguish the
executed true branch from the unexecuted false branch. Any future coverage job
must reject a missing or empty report before invoking a pinned Coveragemap
revision. Synthetic LCOV, target-count proxies, and Starlark transpilation
remain prohibited.
