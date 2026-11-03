# Developer tools

`tools/bazel` runs Bazel from a directory below a module root while keeping that module's disk cache at `<module>/.cache/bazel-disk`.
The checked-in `.bazelrc` uses a relative cache path, which only works from the module root.
The wrapper needs host Python 3.11 or newer and `bazel` or `bazelisk` on `PATH`.

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

The wrapper uses the nearest `MODULE.bazel`, keeps the current directory and arguments, and writes its cache option to the ignored `<module>/.cache/bazel-wrapper.bazelrc`.
Remove all cached state of a module with `rm -rf <module>/.cache`.
