# Module-resolution fixtures

Each directory here is a small consumer module that depends on rules_mkosi through `local_path_override` and checks one aspect of how the module extensions and toolchains resolve in a consumer's dependency graph.
They run outside the root module, so they see rules_mkosi the way a real consumer does.

Run one fixture with:

```console
e2e/module_resolution/test.sh <fixture>
```

`test.sh` checks that the fixture's `.bazelrc` imports `.bazelrc.ci`, then runs the fixture's checks.
CI runs every fixture with each supported Bazel version.

## Toolchain resolution and isolation

These fixtures check that rules_mkosi's static bootstrap executables (the Debian tools launcher and the namespace runner) always build with rules_mkosi's own static musl toolchain from the `llvm` module, that this toolchain never leaks into the consumer's own targets, and that unrelated builds download nothing heavy.

| Fixture | Consumer setup | What `test.sh` checks |
| --- | --- | --- |
| `consumer_isolation` | Registers its own glibc C/C++ toolchain of another compiler (zig through `hermetic_cc_toolchain`, standing in for any consumer toolchain) first, defines its own musl bootstrap platform, and has its own Python line (3.13). | `bazel test //...` (Python stays the consumer's, the bootstrap executables are fully static, the launcher runs, mkosi uses rules_mkosi's Python); the launcher and namespace runner link for `x86_64-linux-musl` with both the consumer's and the default bootstrap platform; rules_mkosi's `kernel_preflight`, an ordinary target rather than a bootstrap executable, links for `x86_64-linux-gnu` with the consumer's toolchain. |
| `rules_cc_first` | Lists `rules_cc` before `rules_mkosi`, so rules_cc's host toolchain is registered ahead of rules_mkosi's, and registers nothing itself. | With `ci/check-lazy-toolchain-fetch.sh`: a plain `sh_test` fetches no heavy repository; the consumer's `cc_library` keeps rules_cc's host toolchain without fetching the `llvm` module; the namespace runner still resolves rules_mkosi's musl toolchain. |
| `llvm_consumer` | Depends on the `llvm` module itself, pinned with `single_version_override`, and registers its toolchains for its own glibc targets. | The lazy-fetch checks above with `--uses-llvm`; the consumer's C binary links dynamically against glibc while the namespace runner links fully statically against musl (`readelf`), both from the same `llvm` module. |

## mkosi toolchain version and naming

These fixtures check the `mkosi.toolchain()` tag of the `mkosi` module extension.
The passing ones query the generated toolchain; the failing ones expect `bazel mod deps` to fail with a specific error.

| Fixture | Consumer setup | Expected result |
| --- | --- | --- |
| `default` | `mkosi.toolchain()` without a version. | Resolves to mkosi 27.1. |
| `explicit` | `mkosi.toolchain(version = "27.1")`. | Resolves to mkosi 27.1. |
| `unsupported` | `mkosi.toolchain(version = "27")`. | Fails: `Unsupported mkosi version 27. Supported versions: 27.1.` |
| `conflicting_root` | Two `mkosi.toolchain()` tags with different names in the root module. | Fails: `Only one mkosi toolchain may be configured.` |
| `nonroot_name` | A dependency, `nonroot_name_dep`, sets `mkosi.toolchain(name = "alternate")`. | Fails: `Only the root module may override the mkosi toolchain name.` |
| `root_dependency` | The root requests mkosi 27.1 and a dependency, `root_dependency_dep`, requests 26. | Fails: `Conflicting mkosi versions: root requests 27.1, dependency requests 26.` |

`nonroot_name_dep` and `root_dependency_dep` are helper modules for these two fixtures, not fixtures themselves.

## Debian snapshots

| Fixture | Consumer setup | Expected result |
| --- | --- | --- |
| `snapshot_name_conflict` | Two `debian_tools.snapshot()` tags with the same repository name `consumer_debian`. | `bazel mod deps` fails because the repository name is already declared. |
