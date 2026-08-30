# End-to-end tests

`e2e/smoke` is an independent Bazelmod project that consumes `rules_mkosi`
through its public API and a `local_path_override`. This catches dependency,
module-extension, toolchain-registration, visibility, and public-label
problems that tests inside the ruleset cannot detect.

The consumer declares the maintained `hermetic_cc_toolchain` as a normal
dependency and registers its generic `@zig_sdk//toolchain:linux_amd64_musl`
toolchain without setting `--platforms` or `--host_platform`. This is the
standard Bzlmod pattern for an extension-provided toolchain: a downstream root
module opts into the maintained default, while its own root registrations can
override it.

The root `.bazelignore` deliberately excludes `e2e/`. A nested `MODULE.bazel`
does not create a package traversal boundary: without that exclusion, a root
`bazel test //...` would load `e2e/smoke` as part of the root repository and
would not exercise its independent module resolution.

Run the root and consumer suites separately using the canonical commands in
[`CONTRIBUTING.md`](../CONTRIBUTING.md). BCR also executes `e2e/smoke` as the
published module's consumer test. The consumer directory pins Bazel 7.7.1
for plain local commands, matching its checked-in format-13 lockfile; CI
explicitly exercises pinned Bazel 8.5.1 and 9.2.0 with lockfile mode off.

`module_resolution` contains checked-in Bazelmod fixtures for extension
selection and failure diagnostics. Run one fixture with
`e2e/module_resolution/test.sh <default|explicit|unsupported|conflicting_root|nonroot_name|root_dependency>`;
CI runs every fixture on Bazel 7.7+, 8, and 9.
