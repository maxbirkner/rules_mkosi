# Contributing

## Prerequisites

- Bazelisk, or the Bazel version in `.bazelversion` (8.5.1).
- [`prek`](https://prek.j178.dev/) 0.5 or newer.
- Host Python 3.11 or newer, only for the [`tools/bazel`](tools/README.md) wrapper.
- A host that meets the [requirements](README.md#requirements), with the Bazel server started without supplementary groups:

  ```console
  bazel shutdown
  sudo -n setpriv --reuid="$(id -u)" --regid="$(id -g)" --clear-groups \
    env HOME="$HOME" PATH="$PATH" USER="$USER" bazel test //...
  ```

- Optional: read-write access to `/dev/kvm` for faster boot tests, granted with a user ACL such as `sudo setfacl -m "u:$USER:rw" /dev/kvm` (group membership is dropped by `--clear-groups`).

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

Bazel 8.5.1 is the default and uses `--lockfile_mode=error` for both committed lockfiles (`MODULE.bazel.lock` and `e2e/smoke/MODULE.bazel.lock`).
Test Bazel 9 without rewriting them:

```console
USE_BAZEL_VERSION=9.2.0 bazel test --config=portable --config=bazel9 //...
```

When dependencies change, regenerate both lockfiles with Bazel 8.5.1 and `--lockfile_mode=update`.
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
| `bazel9` | `--lockfile_mode=off` for Bazel 9. |

Executable tests use only the semantic tags `requires-network`, `requires_kernel_contract`, and `manifest`.
`manual` is reserved for analysis-test subjects that must not run on their own.

### Shell tests

Write shell tests with `runfiles_sh_test` from `//mkosi/tests:runfiles_sh_test.bzl`.
Pass runfiles as `$(rlocationpath ...)` arguments and resolve them in the script with `rlocation "$1"`, which works with and without a runfiles tree.

### Debian locks

The consumer lock fixtures are regenerated from `e2e/smoke` as described in their READMEs; `//mkosi/debian:generate_lock_test` covers the generator.
The built-in `mkosi/debian/debian13.lock.json` is pinned by `DEBIAN_TOOLS_LOCK_SHA256`; changing it also changes the Debian tools archive digest.

## Pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages.
- Public API changes need analysis tests and consumer tests in `e2e/smoke`.
- Releases follow Semantic Versioning, and release notes are generated from pull requests, so describe user-visible and compatibility changes in the title and description.
- Every change to `main` goes through a pull request that passes the `CI conclusion` check.
- Pull requests from contributors without write access need a review from someone with write access.
  Maintainers may bypass review only for their own changes, never to merge an unreviewed outside contribution.
