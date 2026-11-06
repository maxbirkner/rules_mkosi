# mkosi internals in release mode

Release builds, and tracer builds with `debian_snapshot`, run mkosi in-process.
Where mkosi has no option for a release constraint, [`release_patches.py`](../mkosi/private/mkosi_runner/release_patches.py) replaces or wraps an mkosi function.
[`mkosi_contract.py`](../mkosi/private/mkosi_runner/mkosi_contract.py) pins each of these functions for every supported mkosi version, and release mode fails before it patches a different mkosi.

## Patched internals

| mkosi internal | Patch | Why | Upstream alternative in 27.1 |
| --- | --- | --- | --- |
| `mkosi.config:parse_config` | `_FirstConfiguration.parse_config` | Validates the resolved release configuration (seed, epoch, snapshot, declared paths, unsupported settings). Writes the mirror's APT sources for `Release=` and the `Repositories=` components. | Partial. [`ConfigureScripts=`](https://github.com/systemd/mkosi/blob/v27.1/mkosi/resources/man/mkosi.1.md#L2582-L2591) runs in a sandbox, separately for each image, after `[Match]` is evaluated. `mkosi summary --json` would parse the configuration a second time. |
| `mkosi.config:parse_ini` | `_ConfigurationValidator.parse_ini` | Rejects the host-dependent `[Match]` and `[TriggerMatch]` sections in declared files. | None. The sections are gone once the configuration is resolved. |
| `mkosi.context:Context.__init__`, `Context.repository` | `_patch_context_repository` | Serves the snapshot mirror as mkosi's local package repository. [The Debian bootstrap](https://github.com/systemd/mkosi/blob/v27.1/mkosi/distribution/debian.py#L183-L192) maps deb paths back to host paths only below `/var/cache` and `/repository`. | Partial. [`LocalMirror=`](https://github.com/systemd/mkosi/blob/v27.1/mkosi/resources/man/mkosi.1.md#L578-L585) mounts the mirror at its long Bazel path, which APT then embeds in index file names that are limited to 255 bytes. |
| `mkosi.installer:PackageManager.mounts` | `_patch_mounts` | Mounts the mirror at `/repository` read-only instead of read-write. | None. |
| `mkosi.distribution.debian:install_apt_sources` | `_remove_apt_sources` | Leaves the image without APT sources, because the mirror exists only during the build. | Partial. [`RemoveFiles=`](https://github.com/systemd/mkosi/blob/v27.1/mkosi/resources/man/mkosi.1.md#L978-L980) runs near the end of the build, and it would also remove sources that users add. |
| `mkosi:install_sandbox_trees` | `_install_sandbox_trees` | Copies no host `/etc/passwd`, `/etc/group` or resolver files into the sandbox. | None. mkosi copies the host files after it applies `SandboxTrees=`, and `ToolsTreeCertificates=` covers only certificates. |
| `mkosi:make_tar` | `deterministic_make_tar` | Makes the base root archive independent of the file system's directory order. | None. mkosi's tar has no `--sort=name`. |
| `mkosi.manifest:Manifest.record_deb_packages` | `include_base_packages_in_manifest` | Lists the base tree's packages in the manifest of a finalized image. mkosi omits them for `BaseTrees=`. | None. |

The contract also pins:

- the callers through which each patch takes effect;
- the parameters of the mkosi helpers that the replacements call;
- the `Config` fields that the replacements and the validation read.

The mirror's APT sources use a documented mkosi behaviour instead of a patch.
mkosi [does not overwrite](https://github.com/systemd/mkosi/blob/v27.1/mkosi/resources/man/mkosi.1.md#debian-and-other-deb-based-distributions) a `/etc/apt/sources.list.d/mkosi.sources` that the sandbox tree provides.
`//mkosi/tests:mkosi_contract_test` checks this behaviour against the pinned mkosi.

[Issue #90](https://github.com/maxbirkner/rules_mkosi/issues/90) tracks the upstream changes that would make patches unnecessary.

## Upgrading mkosi

1. Add the new version to `MKOSI_VERSIONS` in `mkosi/versions.bzl` and make it `DEFAULT_MKOSI_VERSION`, so that the tests run the new mkosi.
2. Run `bazel test //mkosi/tests:mkosi_contract_test`.
   A version without a contract is compared with the newest contract.
   For each internal that changed, the test prints its new source fingerprint, the patch that replaces or wraps it, and what to re-verify.
3. Read the upstream diff of each listed internal, for example `git diff v27.1 v28 -- mkosi/config.py`, and adapt its patch.
4. Copy the newest entry of `CONTRACTS` in `mkosi_contract.py` under the new version, and update the fingerprints, parameters and fields that you reviewed.
   The test passes once the contract matches.
5. Check the release notes for an option that makes a patch unnecessary.
   Remove the patch only if release images stay byte-identical.
6. Run `ci/verify-release-reproducibility.sh`, `ci/verify-two-stage-cache.sh`, and the complete test suite.
