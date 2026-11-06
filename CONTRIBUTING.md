# Contributing

## Prerequisites

- Bazelisk, or the Bazel version in `.bazelversion`.
- [`prek`](https://prek.j178.dev/) 0.5 or newer.
- Optional: [ShellCheck](https://www.shellcheck.net/) on `PATH`, so prek's actionlint hook also checks workflow `run:` scripts as CI does.
- Host Python 3.11 or newer, only for the [`tools/bazel`](tools/README.md) wrapper.
- A host that meets the [requirements](README.md#requirements).
- Optional: read-write access to `/dev/kvm` for faster boot tests, for example through membership in the `kvm` group.
  `ci/bin/group-free` drops group membership, so a server started through it needs a user ACL such as `sudo setfacl -m "u:$USER:rw" /dev/kvm` instead.

## Checks

```console
prek run --all-files                 # Formatting, linting, spelling, secrets.
prek install                         # Optional: run the same checks as Git hooks.
bazel test //...                     # Root module; excludes e2e/.
ci/regen-lockfiles.sh --check       # Committed lockfiles are current.
bazel run //docs/api:update          # Regenerate the API reference in docs/api.
(cd e2e/smoke && bazel test //...)   # Independent consumer module.
e2e/module_resolution/test.sh consumer_isolation  # One module-resolution fixture.
```

Run Bazel from a module root, or use [`tools/bazel`](tools/README.md) from a subdirectory.
See [`e2e/README.md`](e2e/README.md) for the consumer and module-resolution fixtures.

### API reference

`docs/api` is generated with Stardoc from the docstrings of the public Starlark API: `mkosi/defs.bzl` and the module extensions.
`bazel test //docs/api:all`, part of `bazel test //...`, fails while the committed files differ from the generated ones; regenerate them with `bazel run //docs/api:update`.
Document every public attribute, provider field, and macro argument with its meaning.
A release also uploads the extracted documentation as `rules_mkosi-<tag>.docs.tar.gz`, which the Bazel Central Registry displays.

### Bazel versions and lockfiles

The Bazel version in `.bazelversion` is the default and uses `--lockfile_mode=error` for both committed lockfiles (`MODULE.bazel.lock` and `e2e/smoke/MODULE.bazel.lock`).
CI also tests every other version in `ci/bazel_versions.json`; the lowest one is the supported minimum.
Test Bazel 9 without rewriting the lockfiles:

```console
USE_BAZEL_VERSION=9.x bazel test --config=portable --config=bazel9 //...
```

To change a Bazel version, edit `.bazelversion` or `ci/bazel_versions.json`, then update the copies that the `bazel-versions` prek hook checks.

When dependencies change, regenerate every committed lockfile with `ci/regen-lockfiles.sh`.
It runs `bazel mod deps --lockfile_mode=update` with the Bazel version in `.bazelversion` in each module, because other commands in update mode can drop the entries of extensions they do not evaluate.
Never edit lockfiles by hand.
Module-resolution fixtures have no lockfiles.

### Configs and tags

`.bazelrc.ci` defines execution-policy configs and retries for repository downloads; every nested module imports it, and `e2e/module_resolution/test.sh` checks that each fixture does.
Plain `bazel test //...` runs the complete suite on a capable host.

| Config | Use |
| --- | --- |
| `kernel_preflight` | Runs only the host-kernel preflight (`requires_kernel_contract`); CI runs it before every suite. |
| `qualified` | Linux sandbox, no cached test results, preflight excluded. CI's Bazel 8 lane. |
| `portable` | Like `qualified`, but skips `requires-network` targets. CI's Bazel 9 lane. |
| `manifest` | Runs only `manifest`-tagged tests with `--enable_runfiles=no`. |
| `deterministic` | Offline bootstrap build without cache reuse. |
| `kvm_unavailable` | Hides `/dev/kvm` from tests, so boot tests must fall back to TCG. CI runs `//mkosi/tests:qemu_ovmf_smoke_test` with it. |
| `bazel9` | `--lockfile_mode=off` for Bazel 9, and a link option that protobuf's tools for Stardoc need there. |

Executable tests use only the semantic tags `requires-network`, `requires_kernel_contract`, and `manifest`.
`manual` is reserved for analysis-test subjects that must not run on their own.

Images that tests build set `debian_snapshot`, so builds never download packages and do not depend on `snapshot.debian.org` being available.
Only the manual `//mkosi/tests:debian_subject` is a networked tracer image; build it explicitly to try the network path.

### C and C++ helpers

C and C++ targets use the warning flags in `mkosi/private/c_options.bzl`.
`.bazelrc.warnings` turns them into errors for this repository and its fixtures, but not for consumers, whose compilers may warn differently.
Fix warnings in code rather than suppressing them.

### Shell tests

Write shell tests with `runfiles_sh_test` from `//mkosi/tests:runfiles_sh_test.bzl`.
Pass runfiles as `$(rlocationpath ...)` arguments and resolve them in the script with `rlocation "$1"`, which works with and without a runfiles tree.

### Debian locks

The consumer lock fixtures are regenerated from `e2e/smoke` as described in their READMEs; `//mkosi/debian:generate_lock_test` covers the generator.
The built-in `mkosi/debian/debian13.lock.json` is the Debian tools closure plus the essential packages that release images need, resolved from `mkosi/debian/debian13.spec.json`.
Move it to a new snapshot with one command, optionally together with a new static Python from python-build-standalone:

```console
bazel run //mkosi/debian:refresh_debian_tools -- --snapshot 20260912T080811Z \
  [--python-release 20261026 --python-version 3.14.10]
```

It regenerates the lock, rewrites `mkosi/debian/provenance.bzl` including the archive digest, which it builds `@mkosi_debian_tools//:tree` to compute, and moves the test configurations and README examples to the new snapshot.
Tests read the expected values from `provenance.bzl`.

### mkosi versions

Release mode patches mkosi internals in `mkosi/private/mkosi_runner/release_patches.py`; [mkosi internals](docs/mkosi-internals.md) explains why each patch is needed.
Adding or changing an entry in `mkosi/versions.bzl` requires reviewing those patches against the new mkosi and recording its contract in `mkosi/private/mkosi_runner/mkosi_contract.py`.
Once the new version is the default, `//mkosi/tests:mkosi_contract_test` lists every internal that changed since the newest contract and what to re-verify; follow the [upgrade procedure](docs/mkosi-internals.md#upgrading-mkosi).

## Pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages and pull request titles; the `PR title` check enforces the title, which becomes the squashed commit message.
- Public API changes need analysis tests and consumer tests in `e2e/smoke`.
- Releases follow Semantic Versioning, and release notes are generated from pull requests, so describe user-visible and compatibility changes in the title and description.
  See [BCR publishing](.bcr/README.md) for cutting a release.
- Every change to `main` goes through a pull request that passes the `CI conclusion` check.
- Pull requests from contributors without write access need a review from someone with write access.
  Maintainers may bypass review only for their own changes, never to merge an unreviewed outside contribution.
