# Contributing

## Prerequisites

- Bazelisk, or the Bazel version in `.bazelversion` (8.8.2).
- [`prek`](https://prek.j178.dev/) 0.5 or newer.
- Optional: [ShellCheck](https://www.shellcheck.net/) on `PATH`, so prek's actionlint hook also checks workflow `run:` scripts as CI does.
- Host Python 3.11 or newer, only for the [`tools/bazel`](tools/README.md) wrapper.
- A host that meets the [requirements](README.md#requirements), with the Bazel server started without supplementary groups:

  ```console
  bazel shutdown
  ci/bin/group-free bazel test //...
  ```

- Optional: read-write access to `/dev/kvm` for faster boot tests, granted with a user ACL such as `sudo setfacl -m "u:$USER:rw" /dev/kvm` (`group-free` drops group membership).

## Checks

```console
prek run --all-files                 # Formatting, linting, spelling, secrets.
prek install                         # Optional: run the same checks as Git hooks.
bazel test //...                     # Root module; excludes e2e/.
bazel mod deps --lockfile_mode=error # Committed lockfile is current.
(cd e2e/smoke && bazel test //...)   # Independent consumer module.
e2e/module_resolution/test.sh consumer_isolation  # One module-resolution fixture.
```

Run Bazel from a module root, or use [`tools/bazel`](tools/README.md) from a subdirectory.
See [`e2e/README.md`](e2e/README.md) for the consumer and module-resolution fixtures.

### Bazel versions and lockfiles

Bazel 8.8.2 is the default and uses `--lockfile_mode=error` for both committed lockfiles (`MODULE.bazel.lock` and `e2e/smoke/MODULE.bazel.lock`).
Test Bazel 9 without rewriting them:

```console
USE_BAZEL_VERSION=9.3.1 bazel test --config=portable --config=bazel9 //...
```

When dependencies change, regenerate both lockfiles with Bazel 8.8.2 by running `bazel mod deps --lockfile_mode=update` in the root and in `e2e/smoke`.
Other commands in update mode can drop the entries of extensions they do not evaluate, which `--lockfile_mode=error` then reports as missing.
Never edit lockfiles by hand.
Module-resolution fixtures have no lockfiles.

### Configs and tags

`.bazelrc.ci` defines execution-policy configs; plain `bazel test //...` runs the complete suite on a capable host.

| Config | Use |
| --- | --- |
| `kernel_preflight` | Runs only the host-kernel preflight (`requires_kernel_contract`); CI runs it before every suite. |
| `qualified` | Linux sandbox, no cached test results, preflight excluded. CI's Bazel 8 lane. |
| `portable` | Like `qualified`, but skips `requires-network` (tracer) images. CI's Bazel 9 lane. |
| `manifest` | Runs only `manifest`-tagged tests with `--enable_runfiles=no`. |
| `deterministic` | Offline bootstrap build without cache reuse. |
| `kvm_unavailable` | Hides `/dev/kvm` from tests, so boot tests must fall back to TCG. CI runs `//mkosi/tests:qemu_ovmf_smoke_test` with it. |
| `bazel9` | `--lockfile_mode=off` for Bazel 9. |

Executable tests use only the semantic tags `requires-network`, `requires_kernel_contract`, and `manifest`.
`manual` is reserved for analysis-test subjects that must not run on their own.

### Shell tests

Write shell tests with `runfiles_sh_test` from `//mkosi/tests:runfiles_sh_test.bzl`.
Pass runfiles as `$(rlocationpath ...)` arguments and resolve them in the script with `rlocation "$1"`, which works with and without a runfiles tree.

### Debian locks

The consumer lock fixtures are regenerated from `e2e/smoke` as described in their READMEs; `//mkosi/debian:generate_lock_test` covers the generator.
The built-in `mkosi/debian/debian13.lock.json` is the Debian tools closure plus the essential packages that release images need, resolved from `mkosi/debian/debian13.spec.json`.
To move it to a new snapshot, update the URL in the specification and regenerate the lock:

```console
bazel run //mkosi/debian:generate_lock -- \
  --spec mkosi/debian/debian13.spec.json --output mkosi/debian/debian13.lock.json
```

Then update the snapshot, `DEBIAN_TOOLS_LOCK_SHA256`, and `DEBIAN_TOOLS_ARCHIVE_SHA256` in `mkosi/debian/provenance.bzl`, and the `Snapshot=` of the test configurations that use `@mkosi_debian_snapshot`.
Building `@mkosi_debian_tools//:tree_root` reports the new archive digest.

### mkosi versions

Release mode patches mkosi internals in `mkosi/private/mkosi_runner/release_patches.py`.
Adding or changing an entry in `mkosi/versions.bzl` requires reviewing those patches against the new mkosi and recording its contract in `mkosi/private/mkosi_runner/mkosi_contract.py`.
`//mkosi/tests:mkosi_contract_test` lists every changed internal until then.

## Pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages and pull request titles; the `PR title` check enforces the title, which becomes the squashed commit message.
- Public API changes need analysis tests and consumer tests in `e2e/smoke`.
- Releases follow Semantic Versioning, and release notes are generated from pull requests, so describe user-visible and compatibility changes in the title and description.
- Every change to `main` goes through a pull request that passes the `CI conclusion` check.
- Pull requests from contributors without write access need a review from someone with write access.
  Maintainers may bypass review only for their own changes, never to merge an unreviewed outside contribution.
