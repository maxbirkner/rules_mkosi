# CI helpers

## Goal

This directory contains small validators for repository-specific CI contracts.
Keep helpers here only when a workflow needs logic that is clearer and
testable outside inline shell.

`action_graph_validator.py` checks that Debian toolchain actions do not resolve
host executables through their environment. CI imports it while inspecting
Bazel's action graph. Run its focused unit tests with:

```console
bazel test //ci:action_graph_validator_test
```

Workflow YAML formatting and syntax are maintained by `prek run --all-files`.
This directory deliberately does not duplicate GitHub Actions' interpretation
of workflows or test that Bazel executes targets requested through `//...`.

## Manual image artifacts

Run the `CI` workflow manually with **Upload artifacts** enabled to build and
upload the release-mode test disk, build metadata, partition metadata, and
reproducibility manifest. The Bazel 8 qualified job publishes one
`mkosi-manual-test-<commit>` artifact with a `SHA256SUMS` file. GitHub retains
the artifact for one day.

The input defaults to disabled and does not affect pull request, push, or
scheduled CI runs. It only exposes existing test outputs for manual hardware
testing; it does not create a tag, release, or BCR publication.
