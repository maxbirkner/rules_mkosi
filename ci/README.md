# CI helpers

Small, unit-tested validators for repository-specific CI checks.

`bin/group-free COMMAND...` runs a command without supplementary groups, as image builds require, and fails if any group remains.
CI puts `bin` on `PATH` and runs every Bazel command through it.

| Helper | Checks | Unit tests |
| --- | --- | --- |
| `action_graph_validator.py` | Debian toolchain actions do not resolve host executables. | `//ci:action_graph_validator_test` |
| `verify-two-stage-cache.sh`, `verify_two_stage_cache.py` | A second stamped version of `//mkosi/tests:two_stage_release` re-executes only the finalizing `MkosiImage` action, not `MkosiBase`. | `//ci:verify_two_stage_cache_test` |
| `verify-release-reproducibility.sh`, `verify_reproducibility_execution.py` | Two clean builds of the release images produce identical reproducibility manifests and base digests, and every image action actually executed. | `//ci:verify_reproducibility_execution_test` |
| `check-pr-title.sh` | A pull request title is a Conventional Commit subject of at most 100 characters, because it becomes the squashed commit message. | `//ci:check_pr_title_test` |
| `check_function_size.py` | No Python or Starlark function exceeds 40 lines, counted from `def` to its last line. Longer existing functions are listed in `function_size_baseline.txt` and may only shrink; after shortening one, run `python3 ci/check_function_size.py --update-baseline`. | `//ci:check_function_size_test` |
| `check-starlark-coverage-support.sh` | Whether Bazel can report Starlark coverage; see [Starlark coverage status](../docs/starlark-coverage.md). | — |

Workflow YAML is checked by `prek run --all-files`.

## Duplicated code

`prek run --all-files` fails on any block of at least 8 lines and 60 tokens that appears twice in Python, Starlark (`.bzl` and `BUILD` files), shell, C, or C++ sources.
The check runs [jscpd](https://github.com/kucherenko/jscpd) with the settings in `.jscpd.json`; `npx jscpd@5.4.2 .` lists the clones.
Move shared code into a helper instead of ignoring a clone.
System `#include` lines and `MODULE.bazel` files, which cannot share code, are not compared.

## Manual image artifacts

Run the `CI` workflow manually with **Upload artifacts** enabled to download the release test disk, its build and partition metadata, and its reproducibility manifest with a `SHA256SUMS` file.
The `mkosi-manual-test-<commit>` artifact is kept for one day and is not a release.
