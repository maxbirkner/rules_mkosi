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

The checked-in `.bazelrc` enables a module-local disk cache at
`.cache/bazel-disk`; every standalone module gets a separate cache directory.
These paths are ignored by Git, and the root and `e2e/smoke` paths are also
ignored by Bazel, so they cannot become source inputs or committed artifacts.
The repository-only `.bazelrc.ci`
defines only execution-policy configs: `manifest`, `qualified`, `portable`,
`deterministic`, `kernel_preflight`, and `bazel9`. A plain `bazel test //...`
therefore runs the complete suite on a capable host; CI's Bazel 8 qualified
lane runs every root and consumer test that needs the host kernel contract
after its explicit preflight. Bazel 9 uses `portable` for compatibility and
omits only tests tagged `requires-network`, which the Bazel 8 lane covers:

The rc cache path is intentionally relative because Bazel does not expand
repository-relative substitutions in ordinary option values. Canonical
commands run from a module root. From any nested directory, use the checked-in
`tools/bazel` wrapper. It preserves the caller's directory and relative-label
semantics, stops at the nearest `MODULE.bazel` (whether or not that module has
a `.bazelrc`), and generates an ignored module-local rc containing that
module's absolute `.cache/bazel-disk` path. The wrapper adds only the generated
rc startup option and leaves the caller's arguments untouched, so Bazel parses
all startup options itself. Bazel's rc inheritance applies the `build` cache
setting to `test` and `run`; an explicit command-line `--disk_cache` remains
authoritative.

```console
bazel test //...
USE_BAZEL_VERSION=9.2.0 bazel test --config=portable --config=bazel9 //...
```

The qualified config forces Linux sandbox execution, disables test-result
caching, and excludes only `requires_kernel_contract`, a semantic tag for the
host-only preflight that runs immediately before it. Networked image actions
remain non-cacheable. The `portable` compatibility config excludes only the
semantic `requires-network` mode to avoid rebuilding networked images twice.
The deterministic bootstrap config uses the same semantic exclusion because
its clean-build proof is about offline bootstrap binaries, not mutable image
package downloads.
The independent consumer's manifest config is the one remaining selector: it
uses `--enable_runfiles=no` and the `manifest` tag to exercise the launcher
contract that cannot run in the ordinary runfiles mode.
`manual` is reserved for synthetic analysis subjects (invalid configurations
and deliberately non-booted provider fixtures); these are excluded from
wildcard execution while their companion analysis tests assert the contract.
Executable tests use only the semantic `requires-network`,
`requires_kernel_contract`, and `manifest` tags described above.

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
