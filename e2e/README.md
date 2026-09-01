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
public `mkosi_image` rule. Its real-image build and root-content artifact
validator run as part of the default suite, exercising the network and
host-kernel namespace/mount contract.

The consumer also wraps and registers its own compatible CPython 3.14 runtime
as `//:consumer_python_toolchain`. The
`mkosi_python_override_test` analysis test verifies that
`MkosiToolchainInfo.resolved_python_interpreter` is that consumer target rather
than rules_mkosi's default. The ordinary mkosi version and launcher tests then
execute through the same override, covering rules_mkosi's selection contract
rather than merely testing Bazel registration. The repository root and the
`module_resolution/default` fixture continue to cover the deterministic
zero-configuration default.

The `tree_demo` target additionally consumes a complete configuration directory
and an explicitly typed configuration/source tree through the public API. Its
build and semantic artifact tests also run by default.

`demo_boot_test` is the dedicated UEFI tracer test. It consumes `demo` through
the public `qemu_ovmf_boot_test` macro, boots it with the registered QEMU/OVMF
artifacts and TCG, waits for the exact systemd hostname marker on the guest
serial stream, and verifies the guest's clean `Powering off` shutdown. It runs
in the qualified lane because its image requires the network and host-kernel
contract. The macro creates a native
`managed_python_test` launcher: the direct managed interpreter receives a
private bootstrap first. The bootstrap clears `PATH` and executes the
lifecycle script with `runpy`, followed by the generated JSON configuration.
This preserves a direct ELF launcher while preventing ambient executable
lookup. Consumers that invoke the interpreter as a tool must pass the
bootstrap and lifecycle script explicitly; no public managed-Python binary
wrapper is provided. The runner performs a bounded QMP greeting/capabilities
handshake before classifying QEMU initialization, firmware, guest,
readiness-timeout, and shutdown failures. QMP uses a relative socket name while
QEMU and the handshake run from the scratch directory, avoiding Linux's
AF_UNIX path limit even when `TEST_TMPDIR` is long. Root lifecycle tests drive
the same state machine through launch, QMP, marker, exit, timeout, shutdown,
diagnostic, and cleanup transitions. The macro forwards Bazel's finite
`short`, `moderate`, or `long` timeout category and rejects deadlines that do
not fit inside that category's lifecycle and cleanup budget; `eternal` is not
supported.

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

The consumer `.bazelrc` imports the repository's optional `.bazelrc.ci` and
uses its own ignored `.cache/bazel-disk` directory. Both normal and qualified
commands use `bazel test //...`; configurations change execution policy rather
than maintaining a CI test inventory. Bazel 9's `portable` compatibility config
excludes only the semantic `requires-network` image mode, which Bazel 8 covers.
The separate `manifest` pass uses the one `manifest` selector with
`--enable_runfiles=no` for the launcher contract.

`module_resolution` contains Bazelmod fixtures for extension selection and
failure diagnostics. These fixtures deliberately have no lockfiles and run
with `--lockfile_mode=off` on both supported versions, so dependency state
does not become part of semantic fixture maintenance. Run one fixture with
`e2e/module_resolution/test.sh <default|explicit|unsupported|conflicting_root|nonroot_name|root_dependency>`;
CI runs every fixture on Bazel 8.5.1 and 9.2.0.
