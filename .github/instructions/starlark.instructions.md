---
applyTo: "**/*.bzl,**/BUILD,**/BUILD.bazel,**/MODULE.bazel"
---

# Starlark and Bazel instructions

- Format and lint files with Buildifier.
- Prefer documented providers and toolchains over implicit conventions.
- Give public rules, providers, attributes, and module-extension tags concise
  docstrings.
- Keep user-facing symbols in `mkosi/defs.bzl`; do not expose private helper
  symbols or implementation files.
- Use `cfg = "exec"` for executable tools and include their complete runfiles
  in actions.
- Declare every action input, output, executable, environment requirement, and
  execution constraint. Do not read arbitrary workspace or host paths.
- Prefer `ctx.actions.args()` over manually concatenated command lines.
- Constrain execution platforms through toolchains rather than runtime host
  detection.
- Return focused providers so downstream rules do not infer artifacts from
  filenames.
- Keep module extensions reproducible. Repository downloads require stable
  URLs and integrity hashes.
- Avoid adding dependencies to the runtime module when they are needed only by
  repository development or tests; mark those as `dev_dependency = True`.
- Test providers and registered actions with Skylib `analysistest`. Test
  public consumption through `e2e/smoke`, never by loading private files.
