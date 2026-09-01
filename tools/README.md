# Developer tools

## Goal

This directory contains opt-in, repository-maintained developer commands.
`tools/bazel` provides a safe module-local disk cache when Bazel is invoked
below a module root. This wrapper requires host Python 3.11 or newer and a
`bazel` or `bazelisk` backend on `PATH`; Bazel actions use the separately
registered managed Python 3.14 toolchain.

Use Bazel normally from a module root:

```console
bazel test //...
```

Use the wrapper from a nested package when relative labels must remain relative
to the current directory:

```console
(
  cd mkosi/tests
  ../../tools/bazel test :boot_lifecycle_test
)
(
  cd e2e/smoke
  ../../tools/bazel test //...
)
```

The wrapper stops at the nearest physical `MODULE.bazel`, preserves the caller
directory and arguments, and writes an absolute cache option to
`<module>/.cache/bazel-wrapper.bazelrc`. Cached data is stored in
`<module>/.cache/bazel-disk`. Both paths are ignored. Remove all generated
wrapper state for a module with:

```console
rm -rf /path/to/module/.cache
```

Focused tests cover wrapper-owned argument forwarding, module-boundary,
backend-selection, and symlink-safety behavior. They deliberately do not
retest Bazel's startup-option grammar, rc precedence, or disk-cache
implementation.
