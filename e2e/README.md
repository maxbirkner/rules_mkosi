# End-to-end tests

`e2e/smoke` is an independent Bazelmod project that consumes `rules_mkosi`
through its public API and a `local_path_override`. This catches dependency,
module-extension, toolchain-registration, visibility, and public-label
problems that tests inside the ruleset cannot detect.

The root `.bazelignore` deliberately excludes `e2e/`. A nested `MODULE.bazel`
does not create a package traversal boundary: without that exclusion, a root
`bazel test //...` would load `e2e/smoke` as part of the root repository and
would not exercise its independent module resolution.

Run the root and consumer suites separately using the canonical commands in
[`CONTRIBUTING.md`](../CONTRIBUTING.md). BCR also executes `e2e/smoke` as the
published module's consumer test.
