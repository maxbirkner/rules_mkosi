# CI helpers

Small, unit-tested validators for repository-specific CI checks.

`bin/group-free COMMAND...` runs a command without supplementary groups and fails if any group remains.
`bin/server-identity COMMAND...` runs a command through `group-free` when `SERVER_GROUPS=cleared`, or with the runner's supplementary groups when `SERVER_GROUPS=kept`, and fails if there are none to keep.
CI puts `bin` on `PATH` and runs every Bazel command through one of them, so image builds are covered from Bazel servers with and without supplementary groups.

The consumer suite passes `--sandbox_base` with a bind mount that it remounts `nosuid,nodev`, because self-hosted runners often use `--sandbox_base=/dev/shm`, which is mounted with these flags.
A user namespace locks the flags of the mounts it inherits, so the Debian tools' namespace runner must keep them when it remounts the sandboxed root read-only.
The bind mount is on disk because the suite's parallel image actions do not fit into the hosted runners' RAM-backed `/dev/shm`.
`//mkosi/debian:namespace_runner_test` covers the same contract on a restricted tmpfs in the root suite.

| Helper | Checks | Unit tests |
| --- | --- | --- |
| `action_graph_validator.py` | Debian toolchain actions do not resolve host executables. | `//ci:action_graph_validator_test` |
| `image_environment_validator.py` | Every environment variable of the mkosi image actions has an expected value, so host-dependent variables cannot slip in. | `//ci:image_environment_validator_test` |
| `verify-two-stage-cache.sh`, `verify_two_stage_cache.py` | A second stamped version of `//mkosi/tests:two_stage_release` re-executes only the finalizing `MkosiImage` action, not `MkosiBase`. | `//ci:verify_two_stage_cache_test` |
| `verify-release-reproducibility.sh`, `verify_reproducibility_execution.py` | Two clean builds of the release images, including a compressed erofs root and its update payload, produce identical reproducibility manifests and digests, and every image action actually executed. | `//ci:verify_reproducibility_execution_test` |
| `verify-bootstrap-reproducibility.sh`, `verify_reproducibility_execution.py` | Two builds of the static Debian launcher, namespace runner, and Debian tools archive, each in a fresh output base with a different umask and without action, disk, or remote cache, produce identical digests, sizes, modes, ELF headers, and archive listings; both builds executed every compile, link, and archive action, and neither ran a disabled-action placeholder. | `//ci:verify_reproducibility_execution_test` |
| `check_bazel_versions.py` | The copies of the Bazel versions in `.bazelversion` and `ci/bazel_versions.json` that must stay literal agree with them, and the BCR presubmit checks the lockfile strictly only with the default version. Runs as a prek hook. | `//ci:check_bazel_versions_test` |
| `bcr-presubmit.sh` | The BCR presubmit's `//:stock_runner_tests` of `e2e/smoke` pass from a source archive with a Bazel server that keeps its groups, no repository cache, and snapshot.debian.org blocked. | — |
| `regen-lockfiles.sh` | With `--check`, every committed `MODULE.bazel.lock` is current for the Bazel version in `.bazelversion`; without it, regenerates them. | — |
| `check-pr-title.sh` | A pull request title is a Conventional Commit subject of at most 100 characters, because it becomes the squashed commit message. | `//ci:check_pr_title_test` |
| `check_function_size.py` | No Python or Starlark function exceeds 40 lines, counted from `def` to its last line. Longer existing functions are listed in `function_size_baseline.txt` and may only shrink; after shortening one, run `python3 ci/check_function_size.py --update-baseline`. Entries must not be added or raised compared with `HEAD`, or in CI with the merge base of the pull request (`--base-ref`). | `//ci:check_function_size_test` |
| `check-starlark-coverage-support.sh` | Whether Bazel can report Starlark coverage; see [Starlark coverage status](../docs/starlark-coverage.md). | — |

Workflow YAML is checked by `prek run --all-files`.

## Duplicated code

`prek run --all-files` fails on any block of at least 8 lines and 60 tokens that appears twice in Python, Starlark (`.bzl` and `BUILD` files), shell, C, or C++ sources.
The check runs [jscpd](https://github.com/kucherenko/jscpd) with the settings in `.jscpd.json`; `npx jscpd@5.4.2 .` lists the clones.
Move shared code into a helper instead of ignoring a clone.
Comments, system `#include` lines, and `MODULE.bazel` files, which cannot share code, are not compared.

## Type checking

`prek run --all-files` type-checks the Python files in `ci/`, `mkosi/`, and `tools/` with [mypy](https://mypy-lang.org/) and the settings in `mypy.ini`.
Only annotated functions are checked, so adding type annotations to a function opts it in.

## Manual image artifacts

Run the `CI` workflow manually with **Upload artifacts** enabled to download the release test disk, its build and partition metadata, and its reproducibility manifest with a `SHA256SUMS` file.
The `mkosi-manual-test-<commit>` artifact is kept for one day and is not a release.
