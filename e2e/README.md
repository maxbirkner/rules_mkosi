# End-to-end tests

## `e2e/smoke`

An independent Bazel module that uses rules_mkosi only through its public API and a `local_path_override`.
It catches dependency, module-extension, toolchain-registration, visibility, and public-label problems that root-module tests cannot.
Its `MODULE.bazel` is a working example of the [consumer setup](../README.md#setup), and BCR runs it as the module's test project.

| Targets | Covers |
| --- | --- |
| `demo`, `tree_demo` | Tracer images from a single file and from typed configuration and source trees. |
| `release_demo`, `immutable_demo`, `bios_release_demo` | Release images from the built-in snapshot: plain, with UKI and dm-verity, and legacy BIOS. |
| `consumer_snapshot_demo` | A release image from the consumer-owned `@consumer_debian` lock, which adds `amd64-microcode` from `non-free-firmware`. |
| `sysupdate_base`, `sysupdate_v1` to `sysupdate_v3`, `sysupdate_lifecycle_test` | Three A/B releases finalized from one `mkosi_base`; the test applies an update and a failing update and checks the rollback (see [A/B updates](../docs/sysupdate-ab.md)). |
| `uefi_boot_test`, `bios_boot_test` | Boot tests; `uefi_boot_test` always uses TCG. |
| `mkosi_python_override_test` | A consumer-registered Python 3.14 toolchain replaces the default. |
| `*_public_provider_test`, `*_metadata_test`, `*_artifact_test` | Provider fields and generated artifacts, selected only through public providers. |

Run it from its directory:

```console
cd e2e/smoke
bazel test //...
```

The root `.bazelignore` excludes `e2e/`, so a root `bazel test //...` does not load this module as part of the root repository.
The consumer pins the root module's Bazel version, uses its own lockfile and disk cache, and imports the root `.bazelrc.ci` configs described in [CONTRIBUTING.md](../CONTRIBUTING.md#configs-and-tags).

## `e2e/module_resolution`

Fixtures for module-extension selection and its error messages.
They have no lockfiles and run with `--lockfile_mode=off`.

```console
e2e/module_resolution/test.sh <fixture>
```

| Fixture | Checks |
| --- | --- |
| `default`, `explicit` | Default and explicitly pinned mkosi version. |
| `unsupported` | An unsupported mkosi version fails. |
| `conflicting_root` | Configuring more than one toolchain name fails. |
| `nonroot_name` | A dependency module cannot rename the toolchain. |
| `root_dependency` | Different root and dependency versions fail. |
| `snapshot_name_conflict` | Duplicate `debian_tools.snapshot` names fail. |
| `consumer_isolation` | A consumer with Python 3.13 by default, the `script` bootstrap, and a first-priority glibc toolchain still gets Python 3.14 tools and fully static bootstrap executables through `bootstrap_platform`. |
