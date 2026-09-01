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
