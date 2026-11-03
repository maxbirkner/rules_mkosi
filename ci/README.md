# CI helpers

Small, unit-tested validators for repository-specific CI checks.

| Helper | Checks | Unit tests |
| --- | --- | --- |
| `action_graph_validator.py` | Debian toolchain actions do not resolve host executables. | `//ci:action_graph_validator_test` |
| `verify-two-stage-cache.sh`, `verify_two_stage_cache.py` | A second stamped version of `//mkosi/tests:two_stage_release` re-executes only the finalizing `MkosiImage` action, not `MkosiBase`. | `//ci:verify_two_stage_cache_test` |
| `verify-release-reproducibility.sh`, `verify_reproducibility_execution.py` | Two clean builds of the release images produce identical reproducibility manifests and base digests, and every image action actually executed. | `//ci:verify_reproducibility_execution_test` |
| `check-starlark-coverage-support.sh` | Whether Bazel can report Starlark coverage; see [Starlark coverage status](../docs/starlark-coverage.md). | — |

Workflow YAML is checked by `prek run --all-files`.

## Manual image artifacts

Run the `CI` workflow manually with **Upload artifacts** enabled to download the release test disk, its build and partition metadata, and its reproducibility manifest with a `SHA256SUMS` file.
The `mkosi-manual-test-<commit>` artifact is kept for one day and is not a release.
