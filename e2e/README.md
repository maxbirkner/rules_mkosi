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

The smoke consumer supplies a minimal Debian 13 mkosi configuration to the
public `mkosi_image` rule. Its real-image build and GPT/root-content artifact
validator are manually selected because they require the network and the
host-kernel namespace/mount contract; the ordinary smoke suite remains
portable.

`demo_boot_test` is the dedicated UEFI tracer test. It consumes `demo` through
the dependency graph, boots it with the registered QEMU/OVMF artifacts and
TCG, waits for the exact systemd hostname marker on the guest serial stream,
and verifies the guest's clean `Powering off` shutdown. It is manually
selected because it requires the qualified Linux kernel contract. The test is
a native `managed_python_test`: its TestRunner executable is a symlink to the
registered managed interpreter, not a `rules_python` shell bootstrap or a
`/usr/bin/env` shebang. `boot_launcher_contract_test` executes that same
launcher contract and checks the managed interpreter and user-site isolation.
The runner performs a bounded QMP greeting/capabilities handshake before
classifying QEMU initialization, firmware, guest, readiness-timeout, and
shutdown failures. Its negative cases drive the same `_boot` lifecycle with
real Unix-domain QMP sockets, controlled process exits, deadlines, diagnostic
logs, and cleanup checks rather than testing classification strings alone.

The BCR presubmit has separate Bazel 8 and Bazel 9 tasks. The Bazel 8 task
uses the committed `e2e/smoke/MODULE.bazel.lock` strictly. The Bazel 9 task
passes `--lockfile_mode=off` for compatibility because Bazel 9 uses a newer
format; the repository's normal e2e command remains strict.

The root `.bazelignore` deliberately excludes `e2e/`. A nested `MODULE.bazel`
does not create a package traversal boundary: without that exclusion, a root
`bazel test //...` would load `e2e/smoke` as part of the root repository and
would not exercise its independent module resolution.

Run the root and consumer suites separately using the canonical commands in
[`CONTRIBUTING.md`](../CONTRIBUTING.md). BCR also executes `e2e/smoke` as the
published module's consumer test. The consumer directory pins Bazel 8.5.1
for plain local commands, matching its checked-in Bazel 8 lockfile; CI
explicitly exercises pinned Bazel 8.5.1 strictly and Bazel 9.2.0 with
lockfile mode off.

`module_resolution` contains Bazelmod fixtures for extension selection and
failure diagnostics. These fixtures deliberately have no lockfiles and run
with `--lockfile_mode=off` on both supported versions, so dependency state
does not become part of semantic fixture maintenance. Run one fixture with
`e2e/module_resolution/test.sh <default|explicit|unsupported|conflicting_root|nonroot_name|root_dependency>`;
CI runs every fixture on Bazel 8.5.1 and 9.2.0.
