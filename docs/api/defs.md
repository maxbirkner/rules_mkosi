<!-- Generated with Stardoc: http://skydoc.bazel.build -->

Public API for rules_mkosi.

<a id="debian_snapshot"></a>

## debian_snapshot

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "debian_snapshot")

debian_snapshot(<a href="#debian_snapshot-name">name</a>, <a href="#debian_snapshot-architecture">architecture</a>, <a href="#debian_snapshot-codename">codename</a>, <a href="#debian_snapshot-component_package_records">component_package_records</a>, <a href="#debian_snapshot-component_packages">component_packages</a>,
                <a href="#debian_snapshot-distribution">distribution</a>, <a href="#debian_snapshot-format_version">format_version</a>, <a href="#debian_snapshot-inrelease">inrelease</a>, <a href="#debian_snapshot-lock_sha256">lock_sha256</a>, <a href="#debian_snapshot-metadata_digests">metadata_digests</a>, <a href="#debian_snapshot-package_files">package_files</a>,
                <a href="#debian_snapshot-package_names">package_names</a>, <a href="#debian_snapshot-package_records">package_records</a>, <a href="#debian_snapshot-packages_all_path">packages_all_path</a>, <a href="#debian_snapshot-packages_all_xz">packages_all_xz</a>, <a href="#debian_snapshot-packages_path">packages_path</a>,
                <a href="#debian_snapshot-packages_xz">packages_xz</a>, <a href="#debian_snapshot-release">release</a>, <a href="#debian_snapshot-release_gpg">release_gpg</a>, <a href="#debian_snapshot-release_metadata">release_metadata</a>, <a href="#debian_snapshot-snapshot">snapshot</a>, <a href="#debian_snapshot-snapshot_url">snapshot_url</a>)
</pre>

Materializes an authenticated local APT repository from a pinned Debian snapshot.

Declare it through the debian_tools.snapshot module extension, which generates these attributes from a lock.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="debian_snapshot-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="debian_snapshot-architecture"></a>architecture |  Debian package architecture, such as `amd64`.   | String | optional |  `"amd64"`  |
| <a id="debian_snapshot-codename"></a>codename |  Debian codename, such as `trixie`.   | String | optional |  `"trixie"`  |
| <a id="debian_snapshot-component_package_records"></a>component_package_records |  component\|architecture\|path\|sha256 records for component_packages.   | List of strings | optional |  `[]`  |
| <a id="debian_snapshot-component_packages"></a>component_packages |  Packages.xz indexes of components other than main, aligned with component_package_records.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | optional |  `[]`  |
| <a id="debian_snapshot-distribution"></a>distribution |  mkosi distribution name, `debian`.   | String | optional |  `"debian"`  |
| <a id="debian_snapshot-format_version"></a>format_version |  Repository layout contract version.   | String | optional |  `"debian-snapshot-v1"`  |
| <a id="debian_snapshot-inrelease"></a>inrelease |  Signed InRelease metadata.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="debian_snapshot-lock_sha256"></a>lock_sha256 |  SHA-256 of the lock that pins the repository and packages.   | String | required |  |
| <a id="debian_snapshot-metadata_digests"></a>metadata_digests |  SHA-256 of inrelease, release, release_gpg, packages_xz and packages_all_xz, keyed by those names.   | <a href="https://bazel.build/rules/lib/core/dict">Dictionary: String -> String</a> | required |  |
| <a id="debian_snapshot-package_files"></a>package_files |  Locked .deb files.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | required |  |
| <a id="debian_snapshot-package_names"></a>package_names |  Repository-local names of package_files, in order.   | List of strings | required |  |
| <a id="debian_snapshot-package_records"></a>package_records |  name\|version\|architecture\|filename\|size\|sha256\|local name records of the locked packages.   | List of strings | required |  |
| <a id="debian_snapshot-packages_all_path"></a>packages_all_path |  Repository path of packages_all_xz.   | String | optional |  `"dists/trixie/main/binary-all/Packages.xz"`  |
| <a id="debian_snapshot-packages_all_xz"></a>packages_all_xz |  main binary-all Packages.xz.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="debian_snapshot-packages_path"></a>packages_path |  Repository path of packages_xz.   | String | optional |  `"dists/trixie/main/binary-amd64/Packages.xz"`  |
| <a id="debian_snapshot-packages_xz"></a>packages_xz |  main binary-amd64 Packages.xz.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="debian_snapshot-release"></a>release |  Numeric Debian release, such as `13`.   | String | optional |  `"13"`  |
| <a id="debian_snapshot-release_gpg"></a>release_gpg |  Detached Release.gpg signature.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="debian_snapshot-release_metadata"></a>release_metadata |  Release file of the snapshot, verified against inrelease.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="debian_snapshot-snapshot"></a>snapshot |  Immutable snapshot identifier, such as 20250814T000000Z.   | String | required |  |
| <a id="debian_snapshot-snapshot_url"></a>snapshot_url |  Immutable snapshot URL.   | String | required |  |


<a id="mkosi_base"></a>

## mkosi_base

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_base")

mkosi_base(<a href="#mkosi_base-name">name</a>, <a href="#mkosi_base-config_tree">config_tree</a>, <a href="#mkosi_base-debian_snapshot">debian_snapshot</a>, <a href="#mkosi_base-release_seed">release_seed</a>, <a href="#mkosi_base-release_source_date_epoch">release_source_date_epoch</a>,
           <a href="#mkosi_base-rootfs_payloads">rootfs_payloads</a>)
</pre>

Builds the version-independent root and default initrd of a release image.

Packages are installed from the authenticated debian_snapshot with the network blocked. The base has no partitions,
boot loader or UKI, so it does not depend on an image version: mkosi_image(base = ...) finalizes it for one version,
and a new version reuses the cached base.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="mkosi_base-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="mkosi_base-config_tree"></a>config_tree |  Configuration of the version-independent part of a release, such as Packages=, RemoveFiles= and mkosi.extra content. It is built with Format=tar and Bootable=no and must not set ImageVersion=.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="mkosi_base-debian_snapshot"></a>debian_snapshot |  Authenticated Debian snapshot; the only package source of the network-blocked build.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="mkosi_base-release_seed"></a>release_seed |  Required fixed UUID matching the configuration's resolved Seed=.   | String | optional |  `""`  |
| <a id="mkosi_base-release_source_date_epoch"></a>release_source_date_epoch |  Required non-negative timestamp matching the configuration's resolved SourceDateEpoch=.   | Integer | optional |  `-1`  |
| <a id="mkosi_base-rootfs_payloads"></a>rootfs_payloads |  Version-independent mkosi_rootfs_payload targets installed into the image root.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | optional |  `[]`  |


<a id="mkosi_config_tree"></a>

## mkosi_config_tree

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_config_tree")

mkosi_config_tree(<a href="#mkosi_config_tree-name">name</a>, <a href="#mkosi_config_tree-src">src</a>, <a href="#mkosi_config_tree-srcs">srcs</a>, <a href="#mkosi_config_tree-executable_paths">executable_paths</a>, <a href="#mkosi_config_tree-strip_prefix">strip_prefix</a>, <a href="#mkosi_config_tree-trees">trees</a>)
</pre>

Declares an mkosi configuration tree, or assembles one from src, srcs, and trees.

With only src, the directory is used as is. Otherwise one action copies every input into a new directory with
deterministic modes and timestamps: directories merge, while traversal, absolute paths, duplicate files, and files
that collide with directories fail, at analysis time where the paths are known.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="mkosi_config_tree-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="mkosi_config_tree-src"></a>src |  A configuration directory whose contents form the root of the tree.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="mkosi_config_tree-srcs"></a>srcs |  Files placed at their path relative to the package of the listed target, without strip_prefix, such as glob(["mkosi/**"]).<br><br>Bazel copies what a symlink points to, so the action rejects source files that are, or lie below, a symlink inside their package, such as a link that systemctl enable creates. Map such trees through trees with an mkosi_config_tree whose src keeps relative links and rejects absolute ones. The check only sees symlinks in local or sandboxed execution; remote execution, or a remote-cache hit for an action that ran remotely, may deliver a symlinked source as the content that it points to. Inside a fetched archive repository, a committed link that mimics Bazel's own layout may still be followed, as the archive can ship arbitrary content anyway.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | optional |  `[]`  |
| <a id="mkosi_config_tree-executable_paths"></a>executable_paths |  Relative configuration-tree paths that must be executable.   | List of strings | optional |  `[]`  |
| <a id="mkosi_config_tree-strip_prefix"></a>strip_prefix |  Normalized package-relative directory removed from every srcs path; srcs must all be below it.   | String | optional |  `""`  |
| <a id="mkosi_config_tree-trees"></a>trees |  Targets keyed by the normalized relative directory below which they are placed, such as "mkosi.extra" or "mkosi.initrd.conf/mkosi.extra"; a target may appear under several keys.<br><br>An mkosi_config_tree contributes its contents and executable_paths, and a single generated directory its contents. Any other target contributes its files at their path relative to its package. To place the contents of a source directory, wrap it in an mkosi_config_tree with src.   | Dictionary: String -> Label | optional |  `{}`  |


<a id="mkosi_image"></a>

## mkosi_image

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_image")

mkosi_image(<a href="#mkosi_image-name">name</a>, <a href="#mkosi_image-base">base</a>, <a href="#mkosi_image-config">config</a>, <a href="#mkosi_image-config_tree">config_tree</a>, <a href="#mkosi_image-debian_snapshot">debian_snapshot</a>, <a href="#mkosi_image-firmware">firmware</a>, <a href="#mkosi_image-image_id">image_id</a>, <a href="#mkosi_image-image_version">image_version</a>,
            <a href="#mkosi_image-image_version_file">image_version_file</a>, <a href="#mkosi_image-manifest">manifest</a>, <a href="#mkosi_image-mode">mode</a>, <a href="#mkosi_image-release_seed">release_seed</a>, <a href="#mkosi_image-release_source_date_epoch">release_source_date_epoch</a>,
            <a href="#mkosi_image-rootfs_payloads">rootfs_payloads</a>, <a href="#mkosi_image-source_trees">source_trees</a>, <a href="#mkosi_image-unified_kernel_image">unified_kernel_image</a>, <a href="#mkosi_image-verity">verity</a>)
</pre>

Builds a raw disk image with the pinned mkosi and Debian toolchains.

Tracer mode is never cached and installs packages from the network, or from debian_snapshot with the network
blocked. Release mode installs packages only from an authenticated debian_snapshot with the network blocked, so its
outputs may be cached; with base, it finalizes a cached mkosi_base for one version instead. Builds run locally and
need the Linux namespace and mount capabilities of the host-kernel contract.

Select outputs through MkosiImageInfo; DefaultInfo contains every produced artifact.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="mkosi_image-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="mkosi_image-base"></a>base |  mkosi_base to finalize for this image version instead of installing packages.<br><br>Requires release mode and uefi firmware. The base provides the Debian snapshot, Seed= and SourceDateEpoch=, so debian_snapshot, release_seed and release_source_date_epoch must be unset. The configuration must not install or remove packages and holds only version-dependent settings, such as mkosi.repart/, the boot loader, the UKI and the kernel command line.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="mkosi_image-config"></a>config |  A single mkosi configuration file. Set exactly one of config and config_tree; release mode requires config_tree.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="mkosi_image-config_tree"></a>config_tree |  A complete mkosi configuration tree from mkosi_config_tree.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="mkosi_image-debian_snapshot"></a>debian_snapshot |  Authenticated Debian snapshot to install packages from with the network blocked. Required in release mode unless base is set; optional in tracer mode.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="mkosi_image-firmware"></a>firmware |  "uefi" (default) or "bios", a release-only x86-64 tier that boots with GRUB i386-pc from a GPT BIOS boot partition.   | String | optional |  `"uefi"`  |
| <a id="mkosi_image-image_id"></a>image_id |  os-release IMAGE_ID passed to mkosi as ImageId=, overriding the configuration.<br><br>Lowercase letters, digits, '.', '-' and '_' only. Make variables are expanded.   | String | optional |  `""`  |
| <a id="mkosi_image-image_version"></a>image_version |  os-release IMAGE_VERSION passed to mkosi as ImageVersion=, overriding the configuration.<br><br>Requires image_id and excludes image_version_file. Letters, digits and '.' only, so that systemd-sysupdate can split '<image_id>_<image_version>' and '+'/'-' stay free for systemd-boot boot counting. Make variables are expanded, e.g. image_version = "$(OS_VERSION)" with a TemplateVariableInfo target in `toolchains`.<br><br>With verity = "hash", the populated root and verity partitions must be labelled '<image_id>_<image_version>' and '<image_id>_<image_version>_verity' (repart Label=%M_%A and Label=%M_%A_verity), and inactive A/B slots '_empty', as sysupdate_transfers and sysupdate_payload expect. The verity label must fit the 36-character GPT partition name limit.   | String | optional |  `""`  |
| <a id="mkosi_image-image_version_file"></a>image_version_file |  File containing the os-release IMAGE_VERSION, for versions known only at execution time.<br><br>Use it for build-derived versions, such as a stamped genrule. Requires image_id and excludes image_version. The content must satisfy the image_version constraints, optionally followed by one newline; the actions that read the file enforce them. MkosiImageInfo then sets image_version_file instead of image_version.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="mkosi_image-manifest"></a>manifest |  Also output mkosi's JSON manifest of the installed packages as MkosiImageInfo.manifest.   | Boolean | optional |  `False`  |
| <a id="mkosi_image-mode"></a>mode |  "tracer" (default) is never cached and installs packages from the network, or from debian_snapshot with the network blocked; "release" installs packages only from debian_snapshot or base with the network blocked and may be cached. Both run locally only.   | String | optional |  `"tracer"`  |
| <a id="mkosi_image-release_seed"></a>release_seed |  Fixed UUID matching the configuration's resolved Seed=; required in release mode unless base is set.   | String | optional |  `""`  |
| <a id="mkosi_image-release_source_date_epoch"></a>release_source_date_epoch |  Non-negative timestamp matching the configuration's resolved SourceDateEpoch=; required in release mode unless base is set.   | Integer | optional |  `-1`  |
| <a id="mkosi_image-rootfs_payloads"></a>rootfs_payloads |  mkosi_rootfs_payload targets installed into the image root through mkosi.extra.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | optional |  `[]`  |
| <a id="mkosi_image-source_trees"></a>source_trees |  mkosi_source_tree targets keyed by the normalized relative BuildSources= path, such as "src", at which their contents are staged.   | Dictionary: String -> Label | optional |  `{}`  |
| <a id="mkosi_image-unified_kernel_image"></a>unified_kernel_image |  "none" (default) or "unsigned" to build an unsigned UKI. Requires release mode and uefi firmware; sign it with secure_boot_signing_request.   | String | optional |  `"none"`  |
| <a id="mkosi_image-verity"></a>verity |  "none" (default) or "hash" to split the root into dm-verity data and hash partitions. Requires unified_kernel_image = "unsigned".   | String | optional |  `"none"`  |


<a id="mkosi_reproducibility_manifest"></a>

## mkosi_reproducibility_manifest

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_reproducibility_manifest")

mkosi_reproducibility_manifest(<a href="#mkosi_reproducibility_manifest-name">name</a>, <a href="#mkosi_reproducibility_manifest-image">image</a>)
</pre>

Writes a normalized JSON manifest of the content hashes of a release image's immutable outputs.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="mkosi_reproducibility_manifest-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="mkosi_reproducibility_manifest-image"></a>image |  Release image whose immutable outputs are hashed.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |


<a id="mkosi_rootfs_payload"></a>

## mkosi_rootfs_payload

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_rootfs_payload")

mkosi_rootfs_payload(<a href="#mkosi_rootfs_payload-name">name</a>, <a href="#mkosi_rootfs_payload-src">src</a>, <a href="#mkosi_rootfs_payload-destination">destination</a>, <a href="#mkosi_rootfs_payload-executable_paths">executable_paths</a>)
</pre>

Declares a root-owned file or directory to install into an image.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="mkosi_rootfs_payload-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="mkosi_rootfs_payload-src"></a>src |  A single source or generated file or directory.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="mkosi_rootfs_payload-destination"></a>destination |  Normalized absolute path at which to install the file or the directory contents.   | String | required |  |
| <a id="mkosi_rootfs_payload-executable_paths"></a>executable_paths |  Relative paths in a directory to make executable; use [''] for an executable file.   | List of strings | optional |  `[]`  |


<a id="mkosi_source_tree"></a>

## mkosi_source_tree

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "mkosi_source_tree")

mkosi_source_tree(<a href="#mkosi_source_tree-name">name</a>, <a href="#mkosi_source_tree-src">src</a>, <a href="#mkosi_source_tree-executable_paths">executable_paths</a>)
</pre>

Marks a directory as an mkosi BuildSources= tree.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="mkosi_source_tree-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="mkosi_source_tree-src"></a>src |  A directory mounted for mkosi BuildSources=.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="mkosi_source_tree-executable_paths"></a>executable_paths |  Relative source-tree paths that must be executable.   | List of strings | optional |  `[]`  |


<a id="qemu_executable"></a>

## qemu_executable

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "qemu_executable")

qemu_executable(<a href="#qemu_executable-name">name</a>, <a href="#qemu_executable-qemu">qemu</a>, <a href="#qemu_executable-system_data">system_data</a>)
</pre>

Wraps a QEMU system emulator binary and its runtime data as an executable target.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="qemu_executable-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="qemu_executable-qemu"></a>qemu |  The QEMU system emulator binary.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_executable-system_data"></a>system_data |  QEMU runtime data files.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |


<a id="qemu_ovmf_boot_config"></a>

## qemu_ovmf_boot_config

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "qemu_ovmf_boot_config")

qemu_ovmf_boot_config(<a href="#qemu_ovmf_boot_config-name">name</a>, <a href="#qemu_ovmf_boot_config-accelerator">accelerator</a>, <a href="#qemu_ovmf_boot_config-allow_reboot">allow_reboot</a>, <a href="#qemu_ovmf_boot_config-boot_timeout_seconds">boot_timeout_seconds</a>, <a href="#qemu_ovmf_boot_config-diagnostic_bytes">diagnostic_bytes</a>,
                      <a href="#qemu_ovmf_boot_config-expected_failure_marker">expected_failure_marker</a>, <a href="#qemu_ovmf_boot_config-http_shares">http_shares</a>, <a href="#qemu_ovmf_boot_config-image">image</a>, <a href="#qemu_ovmf_boot_config-machine_args">machine_args</a>, <a href="#qemu_ovmf_boot_config-progress_markers">progress_markers</a>,
                      <a href="#qemu_ovmf_boot_config-qmp_initialization_timeout_seconds">qmp_initialization_timeout_seconds</a>, <a href="#qemu_ovmf_boot_config-read_only_shares">read_only_shares</a>, <a href="#qemu_ovmf_boot_config-readiness_marker">readiness_marker</a>,
                      <a href="#qemu_ovmf_boot_config-secure_boot_code">secure_boot_code</a>, <a href="#qemu_ovmf_boot_config-secure_boot_vars">secure_boot_vars</a>, <a href="#qemu_ovmf_boot_config-shutdown_markers">shutdown_markers</a>, <a href="#qemu_ovmf_boot_config-shutdown_timeout_seconds">shutdown_timeout_seconds</a>,
                      <a href="#qemu_ovmf_boot_config-stop_after_readiness">stop_after_readiness</a>, <a href="#qemu_ovmf_boot_config-test_timeout">test_timeout</a>)
</pre>

Writes the configuration of a qemu_ovmf_boot_test, which declares it as `<name>_config`.

Use it directly only to inspect the validated deadlines through QemuBootConfigInfo.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="qemu_ovmf_boot_config-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="qemu_ovmf_boot_config-accelerator"></a>accelerator |  QEMU accelerator: `auto` (default) or `tcg`.<br><br>`auto` uses KVM when the test can open `/dev/kvm` for reading and writing, and TCG software emulation otherwise. `tcg` always uses TCG. Both use the same guest CPU model. The test log records the accelerator QEMU used.   | String | optional |  `"auto"`  |
| <a id="qemu_ovmf_boot_config-allow_reboot"></a>allow_reboot |  Keep QEMU running across guest reboots instead of treating a reboot as an exit.<br><br>The image snapshot and the copied OVMF variables persist across reboots for the lifetime of the test.   | Boolean | optional |  `False`  |
| <a id="qemu_ovmf_boot_config-boot_timeout_seconds"></a>boot_timeout_seconds |  Seconds that QEMU may take after QMP is ready until readiness_marker appears on the serial console.   | Integer | optional |  `180`  |
| <a id="qemu_ovmf_boot_config-diagnostic_bytes"></a>diagnostic_bytes |  Bytes of the end of each log printed on failure; the retained test outputs are capped at 256 KiB.   | Integer | optional |  `65536`  |
| <a id="qemu_ovmf_boot_config-expected_failure_marker"></a>expected_failure_marker |  Exact serial marker that makes an intentionally failing boot pass before readiness.   | String | optional |  `""`  |
| <a id="qemu_ovmf_boot_config-http_shares"></a>http_shares |  Targets whose files the guest can download from http://10.0.2.100/<path>/, keyed to their path.<br><br>The files of a directory appear at the top of its path. The guest gets a virtio network interface on QEMU's user network, which reaches only this server; configure it with the static address 10.0.2.15/24 or DHCP.   | <a href="https://bazel.build/rules/lib/core/dict">Dictionary: Label -> String</a> | optional |  `{}`  |
| <a id="qemu_ovmf_boot_config-image"></a>image |  mkosi_image whose raw_image is booted through a QEMU snapshot, leaving the image unchanged.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_ovmf_boot_config-machine_args"></a>machine_args |  QEMU machine and memory arguments.   | List of strings | optional |  `["-machine", "q35", "-m", "512M"]`  |
| <a id="qemu_ovmf_boot_config-progress_markers"></a>progress_markers |  Exact serial markers that must appear in this order before readiness_marker.   | List of strings | optional |  `[]`  |
| <a id="qemu_ovmf_boot_config-qmp_initialization_timeout_seconds"></a>qmp_initialization_timeout_seconds |  Seconds that QEMU may take to accept QMP connections.   | Integer | optional |  `15`  |
| <a id="qemu_ovmf_boot_config-read_only_shares"></a>read_only_shares |  Directory targets exposed to the guest as read-only virtio-9p shares, keyed to their mount tags.   | <a href="https://bazel.build/rules/lib/core/dict">Dictionary: Label -> String</a> | optional |  `{}`  |
| <a id="qemu_ovmf_boot_config-readiness_marker"></a>readiness_marker |  Exact serial marker proving guest userspace readiness.<br><br>The default is the hostname line of rules_mkosi's own test images; set it for your image, for example to `systemd[1]: Hostname set to <myhost>.`   | String | optional |  `"systemd[1]: Hostname set to <rules-mkosi-tracer>."`  |
| <a id="qemu_ovmf_boot_config-secure_boot_code"></a>secure_boot_code |  Secure Boot capable OVMF code that replaces the toolchain's OVMF; needs secure_boot_vars.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="qemu_ovmf_boot_config-secure_boot_vars"></a>secure_boot_vars |  Variable store template for secure_boot_code.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="qemu_ovmf_boot_config-shutdown_markers"></a>shutdown_markers |  Exact serial markers proving guest-initiated clean shutdown; one of them must appear.   | List of strings | optional |  `["systemd-shutdown[1]: Powering off.", "reboot: Power down"]`  |
| <a id="qemu_ovmf_boot_config-shutdown_timeout_seconds"></a>shutdown_timeout_seconds |  Seconds after readiness that the guest may take to power off by itself.   | Integer | optional |  `30`  |
| <a id="qemu_ovmf_boot_config-stop_after_readiness"></a>stop_after_readiness |  Terminate QEMU successfully as soon as readiness is observed.   | Boolean | optional |  `False`  |
| <a id="qemu_ovmf_boot_config-test_timeout"></a>test_timeout |  Bazel timeout category of the test: `short`, `moderate`, or `long`.<br><br>The QMP, boot and shutdown deadlines plus a 30 second cleanup margin must fit it (60, 300, or 900 seconds).   | String | optional |  `"moderate"`  |


<a id="qemu_ovmf_smoke_test"></a>

## qemu_ovmf_smoke_test

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "qemu_ovmf_smoke_test")

qemu_ovmf_smoke_test(<a href="#qemu_ovmf_smoke_test-name">name</a>, <a href="#qemu_ovmf_smoke_test-accelerator">accelerator</a>)
</pre>

Starts a minimal QEMU/OVMF process and terminates through QMP.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="qemu_ovmf_smoke_test-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="qemu_ovmf_smoke_test-accelerator"></a>accelerator |  QEMU accelerator: `auto` (default) or `tcg`.<br><br>`auto` uses KVM when the test can open `/dev/kvm` for reading and writing, and TCG software emulation otherwise. `tcg` always uses TCG. Both use the same guest CPU model. The test log records the accelerator QEMU used.   | String | optional |  `"auto"`  |


<a id="qemu_ovmf_toolchain"></a>

## qemu_ovmf_toolchain

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "qemu_ovmf_toolchain")

qemu_ovmf_toolchain(<a href="#qemu_ovmf_toolchain-name">name</a>, <a href="#qemu_ovmf_toolchain-format_version">format_version</a>, <a href="#qemu_ovmf_toolchain-ovmf_code">ovmf_code</a>, <a href="#qemu_ovmf_toolchain-ovmf_code_sha256">ovmf_code_sha256</a>, <a href="#qemu_ovmf_toolchain-ovmf_integrity">ovmf_integrity</a>, <a href="#qemu_ovmf_toolchain-ovmf_sha256">ovmf_sha256</a>,
                    <a href="#qemu_ovmf_toolchain-ovmf_shell">ovmf_shell</a>, <a href="#qemu_ovmf_toolchain-ovmf_shell_sha256">ovmf_shell_sha256</a>, <a href="#qemu_ovmf_toolchain-ovmf_source_url">ovmf_source_url</a>, <a href="#qemu_ovmf_toolchain-ovmf_vars">ovmf_vars</a>, <a href="#qemu_ovmf_toolchain-ovmf_vars_sha256">ovmf_vars_sha256</a>,
                    <a href="#qemu_ovmf_toolchain-ovmf_version">ovmf_version</a>, <a href="#qemu_ovmf_toolchain-qemu_img">qemu_img</a>, <a href="#qemu_ovmf_toolchain-qemu_integrity">qemu_integrity</a>, <a href="#qemu_ovmf_toolchain-qemu_sha256">qemu_sha256</a>, <a href="#qemu_ovmf_toolchain-qemu_source_url">qemu_source_url</a>, <a href="#qemu_ovmf_toolchain-qemu_system">qemu_system</a>,
                    <a href="#qemu_ovmf_toolchain-qemu_version">qemu_version</a>, <a href="#qemu_ovmf_toolchain-seabios">seabios</a>, <a href="#qemu_ovmf_toolchain-seabios_sha256">seabios_sha256</a>, <a href="#qemu_ovmf_toolchain-seabios_version">seabios_version</a>, <a href="#qemu_ovmf_toolchain-system_data">system_data</a>,
                    <a href="#qemu_ovmf_toolchain-system_data_anchor">system_data_anchor</a>)
</pre>

Defines a Linux x86-64 QEMU and OVMF test toolchain.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="qemu_ovmf_toolchain-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="qemu_ovmf_toolchain-format_version"></a>format_version |  Output contract implemented by this toolchain.   | String | optional |  `"qemu-ovmf-v1"`  |
| <a id="qemu_ovmf_toolchain-ovmf_code"></a>ovmf_code |  OVMF_CODE firmware.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_ovmf_toolchain-ovmf_code_sha256"></a>ovmf_code_sha256 |  OVMF_CODE hash.   | String | required |  |
| <a id="qemu_ovmf_toolchain-ovmf_integrity"></a>ovmf_integrity |  OVMF SRI integrity.   | String | required |  |
| <a id="qemu_ovmf_toolchain-ovmf_sha256"></a>ovmf_sha256 |  OVMF SHA-256 hash.   | String | required |  |
| <a id="qemu_ovmf_toolchain-ovmf_shell"></a>ovmf_shell |  UEFI shell executable.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_ovmf_toolchain-ovmf_shell_sha256"></a>ovmf_shell_sha256 |  UEFI shell hash.   | String | required |  |
| <a id="qemu_ovmf_toolchain-ovmf_source_url"></a>ovmf_source_url |  Immutable OVMF URL.   | String | required |  |
| <a id="qemu_ovmf_toolchain-ovmf_vars"></a>ovmf_vars |  OVMF_VARS firmware.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_ovmf_toolchain-ovmf_vars_sha256"></a>ovmf_vars_sha256 |  OVMF_VARS hash.   | String | required |  |
| <a id="qemu_ovmf_toolchain-ovmf_version"></a>ovmf_version |  Pinned OVMF version.   | String | required |  |
| <a id="qemu_ovmf_toolchain-qemu_img"></a>qemu_img |  The qemu-img executable.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_ovmf_toolchain-qemu_integrity"></a>qemu_integrity |  QEMU SRI integrity.   | String | required |  |
| <a id="qemu_ovmf_toolchain-qemu_sha256"></a>qemu_sha256 |  QEMU SHA-256 hash.   | String | required |  |
| <a id="qemu_ovmf_toolchain-qemu_source_url"></a>qemu_source_url |  Immutable QEMU URL.   | String | required |  |
| <a id="qemu_ovmf_toolchain-qemu_system"></a>qemu_system |  The qemu_executable target of the QEMU system emulator.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_ovmf_toolchain-qemu_version"></a>qemu_version |  Pinned QEMU version.   | String | required |  |
| <a id="qemu_ovmf_toolchain-seabios"></a>seabios |  Pinned SeaBIOS firmware.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_ovmf_toolchain-seabios_sha256"></a>seabios_sha256 |  SeaBIOS firmware hash.   | String | required |  |
| <a id="qemu_ovmf_toolchain-seabios_version"></a>seabios_version |  Pinned SeaBIOS build identifier.   | String | required |  |
| <a id="qemu_ovmf_toolchain-system_data"></a>system_data |  QEMU runtime data files.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_ovmf_toolchain-system_data_anchor"></a>system_data_anchor |  QEMU runtime data directory.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |


<a id="qemu_seabios_boot_config"></a>

## qemu_seabios_boot_config

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "qemu_seabios_boot_config")

qemu_seabios_boot_config(<a href="#qemu_seabios_boot_config-name">name</a>, <a href="#qemu_seabios_boot_config-accelerator">accelerator</a>, <a href="#qemu_seabios_boot_config-boot_timeout_seconds">boot_timeout_seconds</a>, <a href="#qemu_seabios_boot_config-diagnostic_bytes">diagnostic_bytes</a>, <a href="#qemu_seabios_boot_config-image">image</a>,
                         <a href="#qemu_seabios_boot_config-machine_args">machine_args</a>, <a href="#qemu_seabios_boot_config-qmp_initialization_timeout_seconds">qmp_initialization_timeout_seconds</a>, <a href="#qemu_seabios_boot_config-readiness_marker">readiness_marker</a>,
                         <a href="#qemu_seabios_boot_config-shutdown_markers">shutdown_markers</a>, <a href="#qemu_seabios_boot_config-shutdown_timeout_seconds">shutdown_timeout_seconds</a>, <a href="#qemu_seabios_boot_config-test_timeout">test_timeout</a>)
</pre>

Writes the configuration of a qemu_seabios_boot_test, which declares it as `<name>_config`.

Use it directly only to inspect the validated deadlines through QemuBootConfigInfo.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="qemu_seabios_boot_config-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="qemu_seabios_boot_config-accelerator"></a>accelerator |  QEMU accelerator: `auto` (default) or `tcg`.<br><br>`auto` uses KVM when the test can open `/dev/kvm` for reading and writing, and TCG software emulation otherwise. `tcg` always uses TCG. Both use the same guest CPU model. The test log records the accelerator QEMU used.   | String | optional |  `"auto"`  |
| <a id="qemu_seabios_boot_config-boot_timeout_seconds"></a>boot_timeout_seconds |  Seconds that QEMU may take after QMP is ready until readiness_marker appears on the serial console.   | Integer | optional |  `180`  |
| <a id="qemu_seabios_boot_config-diagnostic_bytes"></a>diagnostic_bytes |  Bytes of the end of each log printed on failure; the retained test outputs are capped at 256 KiB.   | Integer | optional |  `65536`  |
| <a id="qemu_seabios_boot_config-image"></a>image |  mkosi_image whose raw_image is booted through a QEMU snapshot, leaving the image unchanged.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="qemu_seabios_boot_config-machine_args"></a>machine_args |  QEMU machine and memory arguments.   | List of strings | optional |  `["-machine", "pc", "-m", "512M"]`  |
| <a id="qemu_seabios_boot_config-qmp_initialization_timeout_seconds"></a>qmp_initialization_timeout_seconds |  Seconds that QEMU may take to accept QMP connections.   | Integer | optional |  `15`  |
| <a id="qemu_seabios_boot_config-readiness_marker"></a>readiness_marker |  Exact serial marker proving guest userspace readiness.<br><br>The default is the hostname line of rules_mkosi's own test images; set it for your image, for example to `systemd[1]: Hostname set to <myhost>.`   | String | optional |  `"systemd[1]: Hostname set to <rules-mkosi-bios>."`  |
| <a id="qemu_seabios_boot_config-shutdown_markers"></a>shutdown_markers |  Exact serial markers proving guest-initiated clean shutdown; one of them must appear.   | List of strings | optional |  `["systemd-shutdown[1]: Powering off.", "reboot: Power down"]`  |
| <a id="qemu_seabios_boot_config-shutdown_timeout_seconds"></a>shutdown_timeout_seconds |  Seconds after readiness that the guest may take to power off by itself.   | Integer | optional |  `60`  |
| <a id="qemu_seabios_boot_config-test_timeout"></a>test_timeout |  Bazel timeout category of the test: `short`, `moderate`, or `long`.<br><br>The QMP, boot and shutdown deadlines plus a 30 second cleanup margin must fit it (60, 300, or 900 seconds).   | String | optional |  `"moderate"`  |


<a id="secure_boot_ephemeral_test_fixture"></a>

## secure_boot_ephemeral_test_fixture

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "secure_boot_ephemeral_test_fixture")

secure_boot_ephemeral_test_fixture(<a href="#secure_boot_ephemeral_test_fixture-name">name</a>, <a href="#secure_boot_ephemeral_test_fixture-esp_paths">esp_paths</a>, <a href="#secure_boot_ephemeral_test_fixture-images">images</a>)
</pre>

For tests: signs the UKIs and ESP binaries of images with a throwaway db key and outputs its certificate
and auto-enrollment files for throwaway PK and KEK keys. No key leaves the action.

Use the fixture as both the certificate of secure_boot_signing_request and the signed_binary of
secure_boot_import_response; the import selects the fixture's binary that matches its request.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="secure_boot_ephemeral_test_fixture-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="secure_boot_ephemeral_test_fixture-esp_paths"></a>esp_paths |  ESP binaries of every image to sign as well, such as EFI/systemd/systemd-bootx64.efi.   | List of strings | optional |  `[]`  |
| <a id="secure_boot_ephemeral_test_fixture-images"></a>images |  UEFI release images whose unsigned UKIs, and esp_paths, the fixture signs.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | required |  |


<a id="secure_boot_import_response"></a>

## secure_boot_import_response

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "secure_boot_import_response")

secure_boot_import_response(<a href="#secure_boot_import_response-name">name</a>, <a href="#secure_boot_import_response-request">request</a>, <a href="#secure_boot_import_response-signed_binary">signed_binary</a>)
</pre>

Imports an externally signed UKI or ESP boot binary.

The import fails unless the binary embeds an Authenticode signature by the requested certificate and is otherwise
equivalent to the requested unsigned binary.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="secure_boot_import_response-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="secure_boot_import_response-request"></a>request |  The secure_boot_signing_request that the signer answered.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="secure_boot_import_response-signed_binary"></a>signed_binary |  The signed binary: a single file or a secure_boot_ephemeral_test_fixture.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |


<a id="secure_boot_signed_image"></a>

## secure_boot_signed_image

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "secure_boot_signed_image")

secure_boot_signed_image(<a href="#secure_boot_signed_image-name">name</a>, <a href="#secure_boot_signed_image-auto_enroll_keys">auto_enroll_keys</a>, <a href="#secure_boot_signed_image-image">image</a>, <a href="#secure_boot_signed_image-secure_boot_enroll">secure_boot_enroll</a>, <a href="#secure_boot_signed_image-signed_binaries">signed_binaries</a>)
</pre>

Writes a copy of a UEFI release disk image whose ESP holds signed boot binaries and Secure Boot
auto-enrollment keys.

Only the files of the EFI system partition change. Returns DefaultInfo with the disk image and its JSON metadata, and
the image's MkosiImageInfo with raw_image replaced by the signed disk image.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="secure_boot_signed_image-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="secure_boot_signed_image-auto_enroll_keys"></a>auto_enroll_keys |  PK.auth, KEK.auth, db.auth and optionally dbx.auth, or a secure_boot_ephemeral_test_fixture.<br><br>The public, pre-signed authenticated variables that systemd-boot enrolls from /loader/keys/auto/ when the firmware is in Setup Mode. The build fails unless db trusts the signer of every signed *.efi file and boot loader entry binary on the ESP, including binaries that were already signed in the image.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | optional |  `[]`  |
| <a id="secure_boot_signed_image-image"></a>image |  UEFI release mkosi_image whose signing requests the signed_binaries answer.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="secure_boot_signed_image-secure_boot_enroll"></a>secure_boot_enroll |  systemd-boot's loader.conf secure-boot-enroll mode when auto_enroll_keys are set.<br><br>if-safe enrolls automatically only in a virtual machine; force also enrolls on hardware after a 15 second countdown; manual only adds a boot menu entry.   | String | optional |  `"if-safe"`  |
| <a id="secure_boot_signed_image-signed_binaries"></a>signed_binaries |  secure_boot_import_response targets for the image's UKI and ESP binaries.<br><br>Each replaces every ESP file with the bytes of its unsigned binary. The build fails if a PE/COFF binary on the ESP stays unsigned.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | required |  |


<a id="secure_boot_signing_request"></a>

## secure_boot_signing_request

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "secure_boot_signing_request")

secure_boot_signing_request(<a href="#secure_boot_signing_request-name">name</a>, <a href="#secure_boot_signing_request-certificate">certificate</a>, <a href="#secure_boot_signing_request-esp_path">esp_path</a>, <a href="#secure_boot_signing_request-image">image</a>, <a href="#secure_boot_signing_request-signature_algorithm">signature_algorithm</a>)
</pre>

Creates a request for an external signer to sign one PE/COFF binary of an image with the expected
certificate: the image's unsigned UKI, or a boot binary on its ESP such as systemd-boot.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="secure_boot_signing_request-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="secure_boot_signing_request-certificate"></a>certificate |  Expected signer certificate: a single file or a secure_boot_ephemeral_test_fixture.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="secure_boot_signing_request-esp_path"></a>esp_path |  Path of the PE/COFF binary to sign on the image's ESP, such as EFI/systemd/systemd-bootx64.efi.<br><br>Empty, the default, requests the image's unsigned UKI. Any other value requires a release image, whose ESP the request reads the binary from.   | String | optional |  `""`  |
| <a id="secure_boot_signing_request-image"></a>image |  UEFI release mkosi_image with an unsigned UKI.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="secure_boot_signing_request-signature_algorithm"></a>signature_algorithm |  Required embedded signature algorithm.   | String | optional |  `"authenticode-sha256"`  |


<a id="sysupdate_ephemeral_test_fixture"></a>

## sysupdate_ephemeral_test_fixture

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_ephemeral_test_fixture")

sysupdate_ephemeral_test_fixture(<a href="#sysupdate_ephemeral_test_fixture-name">name</a>, <a href="#sysupdate_ephemeral_test_fixture-payloads">payloads</a>)
</pre>

For tests: signs the SHA256SUMS of payloads with a throwaway OpenPGP key. No key leaves the action.

Use the fixture as both the public_key of sysupdate_signing_request and the signature of sysupdate_import_signature;
the import selects the fixture's signature that verifies. The output group 'keyring' holds a directory with the
certificate as import-pubring.gpg, which a test can share with a guest.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="sysupdate_ephemeral_test_fixture-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="sysupdate_ephemeral_test_fixture-payloads"></a>payloads |  Payloads whose SHA256SUMS the fixture signs.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | required |  |


<a id="sysupdate_import_signature"></a>

## sysupdate_import_signature

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_import_signature")

sysupdate_import_signature(<a href="#sysupdate_import_signature-name">name</a>, <a href="#sysupdate_import_signature-request">request</a>, <a href="#sysupdate_import_signature-signature">signature</a>)
</pre>

Imports an externally created SHA256SUMS.gpg for a payload.

The import fails unless sqv verifies the signature over the requested SHA256SUMS with the requested certificate. It
returns the payload's SysupdatePayloadInfo with signature set; publish the payload directory and SHA256SUMS.gpg side
by side.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="sysupdate_import_signature-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="sysupdate_import_signature-request"></a>request |  The sysupdate_signing_request that the signer answered.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="sysupdate_import_signature-signature"></a>signature |  The detached signature returned by the signer (binary or ASCII-armored), or a sysupdate_ephemeral_test_fixture.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |


<a id="sysupdate_payload"></a>

## sysupdate_payload

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_payload")

sysupdate_payload(<a href="#sysupdate_payload-name">name</a>, <a href="#sysupdate_payload-compression">compression</a>, <a href="#sysupdate_payload-image">image</a>, <a href="#sysupdate_payload-signed_uki">signed_uki</a>)
</pre>

Projects a versioned mkosi_image into an update directory for sysupdate_transfers.

The directory contains '<id>_<version>.root.<uuid>.raw', '<id>_<version>.root-verity.<uuid>.raw',
'<id>_<version>.efi' and a SHA256SUMS manifest of the files as shipped. With compression = 'xz', the root and verity
file names end in '.xz'. The partition UUIDs are those derived from the dm-verity root
hash, which the UKI's roothash= locates at boot, and must match the image's GPT. The root and verity files hold only
the bytes that dm-verity covers, so a minimized read-only root (repart Minimize=best on both partitions) is not
padded to its slot size.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="sysupdate_payload-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="sysupdate_payload-compression"></a>compression |  Compression of the root and verity files: 'xz' appends '.xz' to their names.<br><br>systemd-sysupdate decompresses them while writing the slots; sysupdate_transfers accepts both forms. The UKI stays uncompressed.   | String | optional |  `"none"`  |
| <a id="sysupdate_payload-image"></a>image |  Versioned UEFI release image with an unsigned UKI and dm-verity.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="sysupdate_payload-signed_uki"></a>signed_uki |  Externally signed replacement for the image's unsigned UKI, from secure_boot_import_response.<br><br>The build fails with SYSUPDATE_INVALID unless its signing request was created for this image's unsigned UKI.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |


<a id="sysupdate_signing_request"></a>

## sysupdate_signing_request

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_signing_request")

sysupdate_signing_request(<a href="#sysupdate_signing_request-name">name</a>, <a href="#sysupdate_signing_request-payload">payload</a>, <a href="#sysupdate_signing_request-public_key">public_key</a>)
</pre>

Creates a request for an external signer to sign the SHA256SUMS of a payload with the expected key.

The outputs are SHA256SUMS, the normalized binary certificate signer.pgp, and request.json, which binds the SHA-256 of
SHA256SUMS, the payload files it lists, and the signer's fingerprint.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="sysupdate_signing_request-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="sysupdate_signing_request-payload"></a>payload |  The sysupdate_payload whose SHA256SUMS the signer signs.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="sysupdate_signing_request-public_key"></a>public_key |  Expected signer: one OpenPGP certificate (transferable public key, binary or ASCII-armored), or a sysupdate_ephemeral_test_fixture. Secret keys are rejected.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |


<a id="sysupdate_transfers"></a>

## sysupdate_transfers

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "sysupdate_transfers")

sysupdate_transfers(<a href="#sysupdate_transfers-name">name</a>, <a href="#sysupdate_transfers-boot_attempts">boot_attempts</a>, <a href="#sysupdate_transfers-destination">destination</a>, <a href="#sysupdate_transfers-image_id">image_id</a>, <a href="#sysupdate_transfers-instances">instances</a>, <a href="#sysupdate_transfers-url">url</a>)
</pre>

Generates systemd-sysupdate transfer definitions for A/B root, verity and UKI updates.

Add the target to mkosi_image(rootfs_payloads = [...]) and apply updates with
`systemd-sysupdate --transfer-source=<payload directory> update`, or `systemd-sysupdate update` with url. The running
version is protected, and unless boot_attempts = 0, a release that never reaches boot-complete.target falls back to
the previous one.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="sysupdate_transfers-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="sysupdate_transfers-boot_attempts"></a>boot_attempts |  systemd-boot boot-counting attempts (TriesLeft=) of a newly installed UKI; 0 disables boot counting.   | Integer | optional |  `3`  |
| <a id="sysupdate_transfers-destination"></a>destination |  Image directory receiving the transfer files.   | String | optional |  `"/usr/lib/sysupdate.d"`  |
| <a id="sysupdate_transfers-image_id"></a>image_id |  IMAGE_ID shared by every release of the image.   | String | required |  |
| <a id="sysupdate_transfers-instances"></a>instances |  Number of A/B slots (InstancesMax=).   | Integer | optional |  `2`  |
| <a id="sysupdate_transfers-url"></a>url |  HTTP(S) directory that holds the published payloads, such as 'https://updates.example.com/my-os'.<br><br>Empty, the default, installs from a directory given at run time. With a URL, the transfers download SHA256SUMS, SHA256SUMS.gpg and the files, and verify the signature against the device's /etc/systemd/import-pubring.gpg, or /usr/lib/systemd/import-pubring.gpg without it (Verify=yes). systemd expands specifiers such as %A (the running IMAGE_VERSION) in the URL; write %% for a literal %.   | String | optional |  `""`  |


<a id="DebianSnapshotInfo"></a>

## DebianSnapshotInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "DebianSnapshotInfo")

DebianSnapshotInfo(<a href="#DebianSnapshotInfo-architecture">architecture</a>, <a href="#DebianSnapshotInfo-codename">codename</a>, <a href="#DebianSnapshotInfo-components">components</a>, <a href="#DebianSnapshotInfo-distribution">distribution</a>, <a href="#DebianSnapshotInfo-format_version">format_version</a>, <a href="#DebianSnapshotInfo-inrelease">inrelease</a>,
                   <a href="#DebianSnapshotInfo-lock_sha256">lock_sha256</a>, <a href="#DebianSnapshotInfo-package_files">package_files</a>, <a href="#DebianSnapshotInfo-packages_metadata">packages_metadata</a>, <a href="#DebianSnapshotInfo-release">release</a>, <a href="#DebianSnapshotInfo-release_metadata">release_metadata</a>,
                   <a href="#DebianSnapshotInfo-repository">repository</a>, <a href="#DebianSnapshotInfo-snapshot">snapshot</a>, <a href="#DebianSnapshotInfo-snapshot_url">snapshot_url</a>)
</pre>

Authenticated, content-addressed Debian snapshot repository.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="DebianSnapshotInfo-architecture"></a>architecture |  Debian package architecture, such as `amd64`.    |
| <a id="DebianSnapshotInfo-codename"></a>codename |  Debian codename, such as `trixie`.    |
| <a id="DebianSnapshotInfo-components"></a>components |  Archive components staged in the repository, starting with main.    |
| <a id="DebianSnapshotInfo-distribution"></a>distribution |  mkosi distribution name, `debian`.    |
| <a id="DebianSnapshotInfo-format_version"></a>format_version |  Repository layout contract version.    |
| <a id="DebianSnapshotInfo-inrelease"></a>inrelease |  Authenticated InRelease metadata.    |
| <a id="DebianSnapshotInfo-lock_sha256"></a>lock_sha256 |  Digest of the package and repository lock.    |
| <a id="DebianSnapshotInfo-package_files"></a>package_files |  Locked package files staged in the repository.    |
| <a id="DebianSnapshotInfo-packages_metadata"></a>packages_metadata |  Authenticated Packages metadata of every staged component.    |
| <a id="DebianSnapshotInfo-release"></a>release |  Numeric Debian release, such as `13`.    |
| <a id="DebianSnapshotInfo-release_metadata"></a>release_metadata |  Authenticated Release metadata.    |
| <a id="DebianSnapshotInfo-repository"></a>repository |  TreeArtifact containing the local APT repository.    |
| <a id="DebianSnapshotInfo-snapshot"></a>snapshot |  Immutable snapshot identifier.    |
| <a id="DebianSnapshotInfo-snapshot_url"></a>snapshot_url |  Immutable snapshot URL.    |


<a id="DebianToolsInfo"></a>

## DebianToolsInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "DebianToolsInfo")

DebianToolsInfo(<a href="#DebianToolsInfo-architecture">architecture</a>, <a href="#DebianToolsInfo-archive_sha256">archive_sha256</a>, <a href="#DebianToolsInfo-codename">codename</a>, <a href="#DebianToolsInfo-components">components</a>, <a href="#DebianToolsInfo-distribution">distribution</a>, <a href="#DebianToolsInfo-extractor">extractor</a>,
                <a href="#DebianToolsInfo-format_version">format_version</a>, <a href="#DebianToolsInfo-launcher">launcher</a>, <a href="#DebianToolsInfo-launcher_script">launcher_script</a>, <a href="#DebianToolsInfo-lock_sha256">lock_sha256</a>, <a href="#DebianToolsInfo-provenance">provenance</a>, <a href="#DebianToolsInfo-python">python</a>,
                <a href="#DebianToolsInfo-python_files_to_run">python_files_to_run</a>, <a href="#DebianToolsInfo-python_version">python_version</a>, <a href="#DebianToolsInfo-release">release</a>, <a href="#DebianToolsInfo-required_components">required_components</a>, <a href="#DebianToolsInfo-snapshot">snapshot</a>,
                <a href="#DebianToolsInfo-snapshot_url">snapshot_url</a>, <a href="#DebianToolsInfo-tree">tree</a>, <a href="#DebianToolsInfo-tree_files_to_run">tree_files_to_run</a>, <a href="#DebianToolsInfo-tree_root">tree_root</a>, <a href="#DebianToolsInfo-tree_runfiles">tree_runfiles</a>)
</pre>

Pinned Debian userspace tools and provenance.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="DebianToolsInfo-architecture"></a>architecture |  Debian package architecture, such as `amd64`.    |
| <a id="DebianToolsInfo-archive_sha256"></a>archive_sha256 |  SHA-256 digest of the flattened package archive.    |
| <a id="DebianToolsInfo-codename"></a>codename |  Debian codename, such as `trixie`.    |
| <a id="DebianToolsInfo-components"></a>components |  Checked-in required component manifest.    |
| <a id="DebianToolsInfo-distribution"></a>distribution |  mkosi distribution name, `debian`.    |
| <a id="DebianToolsInfo-extractor"></a>extractor |  Shared strict extraction implementation.    |
| <a id="DebianToolsInfo-format_version"></a>format_version |  Toolchain contract version.    |
| <a id="DebianToolsInfo-launcher"></a>launcher |  FilesToRunProvider for the root-isolated executable launcher.    |
| <a id="DebianToolsInfo-launcher_script"></a>launcher_script |  Click launcher implementation source retained for compatibility.    |
| <a id="DebianToolsInfo-lock_sha256"></a>lock_sha256 |  SHA-256 digest of the checked-in package lockfile.    |
| <a id="DebianToolsInfo-provenance"></a>provenance |  Checked-in package provenance metadata.    |
| <a id="DebianToolsInfo-python"></a>python |  Pinned static Python bootstrap interpreter.    |
| <a id="DebianToolsInfo-python_files_to_run"></a>python_files_to_run |  FilesToRunProvider for the static interpreter.    |
| <a id="DebianToolsInfo-python_version"></a>python_version |  Pinned static Python bootstrap version.    |
| <a id="DebianToolsInfo-release"></a>release |  Numeric Debian release, such as `13`.    |
| <a id="DebianToolsInfo-required_components"></a>required_components |  Initial tracer-required component names.    |
| <a id="DebianToolsInfo-snapshot"></a>snapshot |  Pinned snapshot identifier.    |
| <a id="DebianToolsInfo-snapshot_url"></a>snapshot_url |  Pinned snapshot URL.    |
| <a id="DebianToolsInfo-tree"></a>tree |  Flattened tar archive containing the installed package tree.    |
| <a id="DebianToolsInfo-tree_files_to_run"></a>tree_files_to_run |  FilesToRunProvider preserving tree mappings.    |
| <a id="DebianToolsInfo-tree_root"></a>tree_root |  Extracted Debian tools TreeArtifact.    |
| <a id="DebianToolsInfo-tree_runfiles"></a>tree_runfiles |  Runfiles for the package tree.    |


<a id="ManagedPythonTestInfo"></a>

## ManagedPythonTestInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "ManagedPythonTestInfo")

ManagedPythonTestInfo(<a href="#ManagedPythonTestInfo-source">source</a>, <a href="#ManagedPythonTestInfo-timeout">timeout</a>)
</pre>

Managed interpreter test launcher contract.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="ManagedPythonTestInfo-source"></a>source |  The Python script File that the test runs.    |
| <a id="ManagedPythonTestInfo-timeout"></a>timeout |  Bazel timeout category of the test.    |


<a id="MkosiBaseInfo"></a>

## MkosiBaseInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "MkosiBaseInfo")

MkosiBaseInfo(<a href="#MkosiBaseInfo-debian_snapshot">debian_snapshot</a>, <a href="#MkosiBaseInfo-format_version">format_version</a>, <a href="#MkosiBaseInfo-initrd">initrd</a>, <a href="#MkosiBaseInfo-release_seed">release_seed</a>, <a href="#MkosiBaseInfo-release_source_date_epoch">release_source_date_epoch</a>,
              <a href="#MkosiBaseInfo-root_tree">root_tree</a>)
</pre>

Version-independent root and initrd of a release image, built by mkosi_base.

mkosi_image(base = ...) finalizes it for one image version.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="MkosiBaseInfo-debian_snapshot"></a>debian_snapshot |  DebianSnapshotInfo of the packages in root_tree and initrd.    |
| <a id="MkosiBaseInfo-format_version"></a>format_version |  Contract version, currently mkosi-base-v1.    |
| <a id="MkosiBaseInfo-initrd"></a>initrd |  mkosi's default initrd for root_tree, used as mkosi Initrds=.    |
| <a id="MkosiBaseInfo-release_seed"></a>release_seed |  Seed= UUID shared by the base and its finalization.    |
| <a id="MkosiBaseInfo-release_source_date_epoch"></a>release_source_date_epoch |  SourceDateEpoch= shared by the base and its finalization.    |
| <a id="MkosiBaseInfo-root_tree"></a>root_tree |  Reproducible tar archive of the installed root, used as mkosi BaseTrees=.    |


<a id="MkosiConfigTreeInfo"></a>

## MkosiConfigTreeInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "MkosiConfigTreeInfo")

MkosiConfigTreeInfo(<a href="#MkosiConfigTreeInfo-executable_paths">executable_paths</a>, <a href="#MkosiConfigTreeInfo-is_generated">is_generated</a>, <a href="#MkosiConfigTreeInfo-tree">tree</a>)
</pre>

An mkosi configuration directory.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="MkosiConfigTreeInfo-executable_paths"></a>executable_paths |  Relative paths that must keep their executable mode.    |
| <a id="MkosiConfigTreeInfo-is_generated"></a>is_generated |  Whether the tree is a generated TreeArtifact.    |
| <a id="MkosiConfigTreeInfo-tree"></a>tree |  The configuration directory artifact.    |


<a id="MkosiImageInfo"></a>

## MkosiImageInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "MkosiImageInfo")

MkosiImageInfo(<a href="#MkosiImageInfo-build_metadata">build_metadata</a>, <a href="#MkosiImageInfo-firmware">firmware</a>, <a href="#MkosiImageInfo-format_version">format_version</a>, <a href="#MkosiImageInfo-image">image</a>, <a href="#MkosiImageInfo-image_id">image_id</a>, <a href="#MkosiImageInfo-image_version">image_version</a>,
               <a href="#MkosiImageInfo-image_version_file">image_version_file</a>, <a href="#MkosiImageInfo-manifest">manifest</a>, <a href="#MkosiImageInfo-partition_metadata">partition_metadata</a>, <a href="#MkosiImageInfo-raw_image">raw_image</a>, <a href="#MkosiImageInfo-root_hash">root_hash</a>,
               <a href="#MkosiImageInfo-root_hash_image">root_hash_image</a>, <a href="#MkosiImageInfo-root_image">root_image</a>, <a href="#MkosiImageInfo-uki">uki</a>, <a href="#MkosiImageInfo-uki_metadata">uki_metadata</a>, <a href="#MkosiImageInfo-verity_metadata">verity_metadata</a>)
</pre>

Outputs of mkosi_image.

Select artifacts through these fields rather than DefaultInfo filenames. Every artifact field is a File or None,
and DefaultInfo contains every artifact that is not None. raw_image and build_metadata are always set, release
images add partition_metadata, and UEFI release images add their UKI, split dm-verity artifacts and metadata.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="MkosiImageInfo-build_metadata"></a>build_metadata |  JSON build metadata, schema mkosi-image-build-metadata-v3.<br><br>It records the mode and the output roles, the snapshot and its lock digest when the image is built from debian_snapshot or base, and the seed and source date epoch of release images.    |
| <a id="MkosiImageInfo-firmware"></a>firmware |  Firmware tier: uefi or bios.    |
| <a id="MkosiImageInfo-format_version"></a>format_version |  Contract version, currently mkosi-image-v3.    |
| <a id="MkosiImageInfo-image"></a>image |  Deprecated alias for raw_image.    |
| <a id="MkosiImageInfo-image_id"></a>image_id |  os-release IMAGE_ID set by the rule, or None.    |
| <a id="MkosiImageInfo-image_version"></a>image_version |  os-release IMAGE_VERSION set by the rule during analysis, or None.    |
| <a id="MkosiImageInfo-image_version_file"></a>image_version_file |  File holding the os-release IMAGE_VERSION set through image_version_file, or None.<br><br>The content is letters, digits and '.', optionally followed by one newline. At most one of image_version and image_version_file is set.    |
| <a id="MkosiImageInfo-manifest"></a>manifest |  mkosi's JSON manifest of the installed packages, including those of a finalized base, when the rule sets manifest = True, or None.    |
| <a id="MkosiImageInfo-partition_metadata"></a>partition_metadata |  Validated, normalized GPT partition layout JSON of a release image, or None.    |
| <a id="MkosiImageInfo-raw_image"></a>raw_image |  The raw disk image.    |
| <a id="MkosiImageInfo-root_hash"></a>root_hash |  File with the lowercase hex dm-verity root hash when verity = "hash", or None.    |
| <a id="MkosiImageInfo-root_hash_image"></a>root_hash_image |  Split dm-verity hash partition when verity = "hash", or None.    |
| <a id="MkosiImageInfo-root_image"></a>root_image |  Split root filesystem partition when verity = "hash", or None.    |
| <a id="MkosiImageInfo-uki"></a>uki |  The unsigned Unified Kernel Image when unified_kernel_image = "unsigned", or None.    |
| <a id="MkosiImageInfo-uki_metadata"></a>uki_metadata |  Normalized JSON metadata of the UKI's PE sections, or None.    |
| <a id="MkosiImageInfo-verity_metadata"></a>verity_metadata |  Normalized JSON linking the root and hash partitions to root_hash, or None.    |


<a id="MkosiQemuToolchainInfo"></a>

## MkosiQemuToolchainInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "MkosiQemuToolchainInfo")

MkosiQemuToolchainInfo(<a href="#MkosiQemuToolchainInfo-execution_cpu">execution_cpu</a>, <a href="#MkosiQemuToolchainInfo-execution_os">execution_os</a>, <a href="#MkosiQemuToolchainInfo-format_version">format_version</a>, <a href="#MkosiQemuToolchainInfo-ovmf_code">ovmf_code</a>, <a href="#MkosiQemuToolchainInfo-ovmf_code_sha256">ovmf_code_sha256</a>,
                       <a href="#MkosiQemuToolchainInfo-ovmf_integrity">ovmf_integrity</a>, <a href="#MkosiQemuToolchainInfo-ovmf_sha256">ovmf_sha256</a>, <a href="#MkosiQemuToolchainInfo-ovmf_shell">ovmf_shell</a>, <a href="#MkosiQemuToolchainInfo-ovmf_shell_sha256">ovmf_shell_sha256</a>, <a href="#MkosiQemuToolchainInfo-ovmf_source_url">ovmf_source_url</a>,
                       <a href="#MkosiQemuToolchainInfo-ovmf_vars">ovmf_vars</a>, <a href="#MkosiQemuToolchainInfo-ovmf_vars_sha256">ovmf_vars_sha256</a>, <a href="#MkosiQemuToolchainInfo-ovmf_version">ovmf_version</a>, <a href="#MkosiQemuToolchainInfo-qemu_files_to_run">qemu_files_to_run</a>, <a href="#MkosiQemuToolchainInfo-qemu_img">qemu_img</a>,
                       <a href="#MkosiQemuToolchainInfo-qemu_integrity">qemu_integrity</a>, <a href="#MkosiQemuToolchainInfo-qemu_runfiles">qemu_runfiles</a>, <a href="#MkosiQemuToolchainInfo-qemu_sha256">qemu_sha256</a>, <a href="#MkosiQemuToolchainInfo-qemu_source_url">qemu_source_url</a>, <a href="#MkosiQemuToolchainInfo-qemu_system">qemu_system</a>,
                       <a href="#MkosiQemuToolchainInfo-qemu_version">qemu_version</a>, <a href="#MkosiQemuToolchainInfo-seabios">seabios</a>, <a href="#MkosiQemuToolchainInfo-seabios_sha256">seabios_sha256</a>, <a href="#MkosiQemuToolchainInfo-seabios_version">seabios_version</a>, <a href="#MkosiQemuToolchainInfo-system_data_anchor">system_data_anchor</a>,
                       <a href="#MkosiQemuToolchainInfo-system_data_files">system_data_files</a>)
</pre>

Information used by tests to execute QEMU with OVMF.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="MkosiQemuToolchainInfo-execution_cpu"></a>execution_cpu |  Execution CPU constraint.    |
| <a id="MkosiQemuToolchainInfo-execution_os"></a>execution_os |  Execution operating system constraint.    |
| <a id="MkosiQemuToolchainInfo-format_version"></a>format_version |  String identifying the toolchain output contract.    |
| <a id="MkosiQemuToolchainInfo-ovmf_code"></a>ovmf_code |  OVMF_CODE firmware artifact.    |
| <a id="MkosiQemuToolchainInfo-ovmf_code_sha256"></a>ovmf_code_sha256 |  SHA-256 hash of OVMF_CODE.fd.    |
| <a id="MkosiQemuToolchainInfo-ovmf_integrity"></a>ovmf_integrity |  SRI integrity string of the OVMF artifact.    |
| <a id="MkosiQemuToolchainInfo-ovmf_sha256"></a>ovmf_sha256 |  SHA-256 integrity hash of the OVMF artifact.    |
| <a id="MkosiQemuToolchainInfo-ovmf_shell"></a>ovmf_shell |  UEFI shell executable used for readiness.    |
| <a id="MkosiQemuToolchainInfo-ovmf_shell_sha256"></a>ovmf_shell_sha256 |  SHA-256 hash of shell.efi.    |
| <a id="MkosiQemuToolchainInfo-ovmf_source_url"></a>ovmf_source_url |  Immutable OVMF artifact URL.    |
| <a id="MkosiQemuToolchainInfo-ovmf_vars"></a>ovmf_vars |  OVMF_VARS firmware artifact.    |
| <a id="MkosiQemuToolchainInfo-ovmf_vars_sha256"></a>ovmf_vars_sha256 |  SHA-256 hash of OVMF_VARS.fd.    |
| <a id="MkosiQemuToolchainInfo-ovmf_version"></a>ovmf_version |  Pinned OVMF release version.    |
| <a id="MkosiQemuToolchainInfo-qemu_files_to_run"></a>qemu_files_to_run |  FilesToRunProvider for the QEMU executable.    |
| <a id="MkosiQemuToolchainInfo-qemu_img"></a>qemu_img |  The qemu-img executable.    |
| <a id="MkosiQemuToolchainInfo-qemu_integrity"></a>qemu_integrity |  SRI integrity string of the QEMU system artifact.    |
| <a id="MkosiQemuToolchainInfo-qemu_runfiles"></a>qemu_runfiles |  Runfiles needed by the QEMU executable.    |
| <a id="MkosiQemuToolchainInfo-qemu_sha256"></a>qemu_sha256 |  SHA-256 integrity hash of the QEMU system artifact.    |
| <a id="MkosiQemuToolchainInfo-qemu_source_url"></a>qemu_source_url |  Immutable QEMU artifact URL.    |
| <a id="MkosiQemuToolchainInfo-qemu_system"></a>qemu_system |  The QEMU system executable.    |
| <a id="MkosiQemuToolchainInfo-qemu_version"></a>qemu_version |  Pinned QEMU prebuilt release version.    |
| <a id="MkosiQemuToolchainInfo-seabios"></a>seabios |  SeaBIOS x86 firmware artifact.    |
| <a id="MkosiQemuToolchainInfo-seabios_sha256"></a>seabios_sha256 |  SHA-256 hash of the SeaBIOS artifact.    |
| <a id="MkosiQemuToolchainInfo-seabios_version"></a>seabios_version |  Pinned SeaBIOS build identifier.    |
| <a id="MkosiQemuToolchainInfo-system_data_anchor"></a>system_data_anchor |  The QEMU share/qemu data directory.    |
| <a id="MkosiQemuToolchainInfo-system_data_files"></a>system_data_files |  Files in the QEMU data directory.    |


<a id="MkosiRootfsPayloadInfo"></a>

## MkosiRootfsPayloadInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "MkosiRootfsPayloadInfo")

MkosiRootfsPayloadInfo(<a href="#MkosiRootfsPayloadInfo-artifact">artifact</a>, <a href="#MkosiRootfsPayloadInfo-destination">destination</a>, <a href="#MkosiRootfsPayloadInfo-executable_paths">executable_paths</a>, <a href="#MkosiRootfsPayloadInfo-is_generated">is_generated</a>, <a href="#MkosiRootfsPayloadInfo-is_tree">is_tree</a>)
</pre>

A file or directory installed at an absolute destination in the image root.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="MkosiRootfsPayloadInfo-artifact"></a>artifact |  The file or directory artifact.    |
| <a id="MkosiRootfsPayloadInfo-destination"></a>destination |  Normalized absolute destination in the image root.    |
| <a id="MkosiRootfsPayloadInfo-executable_paths"></a>executable_paths |  Relative paths in a directory, or [''] for a file, that must be executable.    |
| <a id="MkosiRootfsPayloadInfo-is_generated"></a>is_generated |  Whether artifact is generated rather than a source artifact.    |
| <a id="MkosiRootfsPayloadInfo-is_tree"></a>is_tree |  Whether artifact is a directory whose contents are installed at destination.    |


<a id="MkosiSourceTreeInfo"></a>

## MkosiSourceTreeInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "MkosiSourceTreeInfo")

MkosiSourceTreeInfo(<a href="#MkosiSourceTreeInfo-executable_paths">executable_paths</a>, <a href="#MkosiSourceTreeInfo-is_generated">is_generated</a>, <a href="#MkosiSourceTreeInfo-tree">tree</a>)
</pre>

A directory mounted for mkosi BuildSources=.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="MkosiSourceTreeInfo-executable_paths"></a>executable_paths |  Relative paths that must keep their executable mode.    |
| <a id="MkosiSourceTreeInfo-is_generated"></a>is_generated |  Whether the tree is a generated TreeArtifact.    |
| <a id="MkosiSourceTreeInfo-tree"></a>tree |  The source directory artifact.    |


<a id="MkosiToolchainInfo"></a>

## MkosiToolchainInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "MkosiToolchainInfo")

MkosiToolchainInfo(<a href="#MkosiToolchainInfo-executable">executable</a>, <a href="#MkosiToolchainInfo-files_to_run">files_to_run</a>, <a href="#MkosiToolchainInfo-format_version">format_version</a>, <a href="#MkosiToolchainInfo-integrity">integrity</a>, <a href="#MkosiToolchainInfo-name">name</a>, <a href="#MkosiToolchainInfo-pefile">pefile</a>, <a href="#MkosiToolchainInfo-python">python</a>,
                   <a href="#MkosiToolchainInfo-python_files_to_run">python_files_to_run</a>, <a href="#MkosiToolchainInfo-python_runtime_files">python_runtime_files</a>, <a href="#MkosiToolchainInfo-python_version">python_version</a>,
                   <a href="#MkosiToolchainInfo-resolved_python_interpreter">resolved_python_interpreter</a>, <a href="#MkosiToolchainInfo-resolved_python_version">resolved_python_version</a>, <a href="#MkosiToolchainInfo-runfiles">runfiles</a>, <a href="#MkosiToolchainInfo-runfiles_files">runfiles_files</a>,
                   <a href="#MkosiToolchainInfo-script">script</a>, <a href="#MkosiToolchainInfo-source_sha256">source_sha256</a>, <a href="#MkosiToolchainInfo-source_url">source_url</a>, <a href="#MkosiToolchainInfo-version">version</a>)
</pre>

Information used to execute an mkosi image build.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="MkosiToolchainInfo-executable"></a>executable |  The Bazel-managed Python executable used to run mkosi.    |
| <a id="MkosiToolchainInfo-files_to_run"></a>files_to_run |  Compatibility alias for the managed Python FilesToRunProvider.    |
| <a id="MkosiToolchainInfo-format_version"></a>format_version |  String identifying the toolchain output contract.    |
| <a id="MkosiToolchainInfo-integrity"></a>integrity |  SRI integrity string for the mkosi source archive.    |
| <a id="MkosiToolchainInfo-name"></a>name |  Logical name of the selected toolchain.    |
| <a id="MkosiToolchainInfo-pefile"></a>pefile |  The pinned pefile module used by mkosi.    |
| <a id="MkosiToolchainInfo-python"></a>python |  The Bazel-managed Python executable used to run mkosi.    |
| <a id="MkosiToolchainInfo-python_files_to_run"></a>python_files_to_run |  FilesToRunProvider for the managed Python executable.    |
| <a id="MkosiToolchainInfo-python_runtime_files"></a>python_runtime_files |  Complete files from the managed Python runtime.    |
| <a id="MkosiToolchainInfo-python_version"></a>python_version |  Required Bazel-managed Python major/minor line.    |
| <a id="MkosiToolchainInfo-resolved_python_interpreter"></a>resolved_python_interpreter |  Original interpreter selected by Python toolchain resolution.    |
| <a id="MkosiToolchainInfo-resolved_python_version"></a>resolved_python_version |  Concrete version supplied by the selected Python toolchain.    |
| <a id="MkosiToolchainInfo-runfiles"></a>runfiles |  Runfiles object preserving mappings for mkosi and its dependencies.    |
| <a id="MkosiToolchainInfo-runfiles_files"></a>runfiles_files |  Complete mkosi source and dependency runfiles.    |
| <a id="MkosiToolchainInfo-script"></a>script |  The exact mkosi Python entrypoint script.    |
| <a id="MkosiToolchainInfo-source_sha256"></a>source_sha256 |  SHA-256 integrity hash of the mkosi source archive.    |
| <a id="MkosiToolchainInfo-source_url"></a>source_url |  Immutable URL used to fetch the mkosi source.    |
| <a id="MkosiToolchainInfo-version"></a>version |  Pinned mkosi version.    |


<a id="QemuBootConfigInfo"></a>

## QemuBootConfigInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "QemuBootConfigInfo")

QemuBootConfigInfo(<a href="#QemuBootConfigInfo-boot_timeout_seconds">boot_timeout_seconds</a>, <a href="#QemuBootConfigInfo-cleanup_margin_seconds">cleanup_margin_seconds</a>, <a href="#QemuBootConfigInfo-qmp_initialization_timeout_seconds">qmp_initialization_timeout_seconds</a>,
                   <a href="#QemuBootConfigInfo-shutdown_timeout_seconds">shutdown_timeout_seconds</a>, <a href="#QemuBootConfigInfo-test_timeout">test_timeout</a>)
</pre>

Validated lifecycle deadlines of a QEMU boot test configuration.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="QemuBootConfigInfo-boot_timeout_seconds"></a>boot_timeout_seconds |  Deadline for the readiness marker.    |
| <a id="QemuBootConfigInfo-cleanup_margin_seconds"></a>cleanup_margin_seconds |  Time reserved within the test timeout for cleanup.    |
| <a id="QemuBootConfigInfo-qmp_initialization_timeout_seconds"></a>qmp_initialization_timeout_seconds |  Deadline for QMP to become ready.    |
| <a id="QemuBootConfigInfo-shutdown_timeout_seconds"></a>shutdown_timeout_seconds |  Deadline for the clean shutdown.    |
| <a id="QemuBootConfigInfo-test_timeout"></a>test_timeout |  Bazel test timeout category.    |


<a id="QemuOvmfBootConfigInfo"></a>

## QemuOvmfBootConfigInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "QemuOvmfBootConfigInfo")

QemuOvmfBootConfigInfo(<a href="#QemuOvmfBootConfigInfo-boot_timeout_seconds">boot_timeout_seconds</a>, <a href="#QemuOvmfBootConfigInfo-cleanup_margin_seconds">cleanup_margin_seconds</a>,
                       <a href="#QemuOvmfBootConfigInfo-qmp_initialization_timeout_seconds">qmp_initialization_timeout_seconds</a>, <a href="#QemuOvmfBootConfigInfo-shutdown_timeout_seconds">shutdown_timeout_seconds</a>, <a href="#QemuOvmfBootConfigInfo-test_timeout">test_timeout</a>)
</pre>

Validated lifecycle deadlines of a QEMU boot test configuration.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="QemuOvmfBootConfigInfo-boot_timeout_seconds"></a>boot_timeout_seconds |  Deadline for the readiness marker.    |
| <a id="QemuOvmfBootConfigInfo-cleanup_margin_seconds"></a>cleanup_margin_seconds |  Time reserved within the test timeout for cleanup.    |
| <a id="QemuOvmfBootConfigInfo-qmp_initialization_timeout_seconds"></a>qmp_initialization_timeout_seconds |  Deadline for QMP to become ready.    |
| <a id="QemuOvmfBootConfigInfo-shutdown_timeout_seconds"></a>shutdown_timeout_seconds |  Deadline for the clean shutdown.    |
| <a id="QemuOvmfBootConfigInfo-test_timeout"></a>test_timeout |  Bazel test timeout category.    |


<a id="SecureBootEphemeralTestFixtureInfo"></a>

## SecureBootEphemeralTestFixtureInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "SecureBootEphemeralTestFixtureInfo")

SecureBootEphemeralTestFixtureInfo(<a href="#SecureBootEphemeralTestFixtureInfo-auto_enroll_keys">auto_enroll_keys</a>, <a href="#SecureBootEphemeralTestFixtureInfo-certificate">certificate</a>, <a href="#SecureBootEphemeralTestFixtureInfo-execution_requirements">execution_requirements</a>,
                                   <a href="#SecureBootEphemeralTestFixtureInfo-signed_binaries">signed_binaries</a>)
</pre>

Public outputs from one action-private ephemeral signing operation.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="SecureBootEphemeralTestFixtureInfo-auto_enroll_keys"></a>auto_enroll_keys |  PK.auth (self-signed), KEK.auth (signed by PK) and db.auth (signed by KEK) of the keys.    |
| <a id="SecureBootEphemeralTestFixtureInfo-certificate"></a>certificate |  Ephemeral public certificate.    |
| <a id="SecureBootEphemeralTestFixtureInfo-execution_requirements"></a>execution_requirements |  No-remote, no-cache action policy.    |
| <a id="SecureBootEphemeralTestFixtureInfo-signed_binaries"></a>signed_binaries |  Authenticode-signed test binaries, one per requested UKI and ESP file.    |


<a id="SecureBootSignedBinaryInfo"></a>

## SecureBootSignedBinaryInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "SecureBootSignedBinaryInfo")

SecureBootSignedBinaryInfo(<a href="#SecureBootSignedBinaryInfo-certificate">certificate</a>, <a href="#SecureBootSignedBinaryInfo-esp_path">esp_path</a>, <a href="#SecureBootSignedBinaryInfo-format_version">format_version</a>, <a href="#SecureBootSignedBinaryInfo-request">request</a>, <a href="#SecureBootSignedBinaryInfo-signed_binary">signed_binary</a>,
                           <a href="#SecureBootSignedBinaryInfo-verification_metadata">verification_metadata</a>)
</pre>

Authenticode-verified, firmware-consumable PE/COFF binary: a UKI or a boot binary from an image's ESP.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="SecureBootSignedBinaryInfo-certificate"></a>certificate |  DER certificate that signed the binary.    |
| <a id="SecureBootSignedBinaryInfo-esp_path"></a>esp_path |  ESP path of the binary, or the empty string for a UKI.    |
| <a id="SecureBootSignedBinaryInfo-format_version"></a>format_version |  Provider schema, mkosi-secure-boot-signed-binary-v3.    |
| <a id="SecureBootSignedBinaryInfo-request"></a>request |  Verified request.    |
| <a id="SecureBootSignedBinaryInfo-signed_binary"></a>signed_binary |  Verified signed PE/COFF binary.    |
| <a id="SecureBootSignedBinaryInfo-verification_metadata"></a>verification_metadata |  Verification and equivalence metadata.    |


<a id="SecureBootSigningRequestInfo"></a>

## SecureBootSigningRequestInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "SecureBootSigningRequestInfo")

SecureBootSigningRequestInfo(<a href="#SecureBootSigningRequestInfo-certificate">certificate</a>, <a href="#SecureBootSigningRequestInfo-esp_path">esp_path</a>, <a href="#SecureBootSigningRequestInfo-format_version">format_version</a>, <a href="#SecureBootSigningRequestInfo-request">request</a>, <a href="#SecureBootSigningRequestInfo-request_digest">request_digest</a>,
                             <a href="#SecureBootSigningRequestInfo-signature_algorithm">signature_algorithm</a>, <a href="#SecureBootSigningRequestInfo-unsigned_binary">unsigned_binary</a>)
</pre>

Typed immutable request for an external Secure Boot signer.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="SecureBootSigningRequestInfo-certificate"></a>certificate |  Expected public signer certificate.    |
| <a id="SecureBootSigningRequestInfo-esp_path"></a>esp_path |  ESP path of the requested binary, or the empty string for the image's UKI.    |
| <a id="SecureBootSigningRequestInfo-format_version"></a>format_version |  Request schema, mkosi-secure-boot-signing-request-v3.    |
| <a id="SecureBootSigningRequestInfo-request"></a>request |  Canonical JSON request.    |
| <a id="SecureBootSigningRequestInfo-request_digest"></a>request_digest |  Canonical request SHA-256.    |
| <a id="SecureBootSigningRequestInfo-signature_algorithm"></a>signature_algorithm |  Required embedded Authenticode algorithm.    |
| <a id="SecureBootSigningRequestInfo-unsigned_binary"></a>unsigned_binary |  Exact unsigned PE/COFF binary bound by the request.    |


<a id="SysupdateEphemeralTestFixtureInfo"></a>

## SysupdateEphemeralTestFixtureInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "SysupdateEphemeralTestFixtureInfo")

SysupdateEphemeralTestFixtureInfo(<a href="#SysupdateEphemeralTestFixtureInfo-execution_requirements">execution_requirements</a>, <a href="#SysupdateEphemeralTestFixtureInfo-keyring">keyring</a>, <a href="#SysupdateEphemeralTestFixtureInfo-public_key">public_key</a>, <a href="#SysupdateEphemeralTestFixtureInfo-signatures">signatures</a>)
</pre>

Public outputs from one action-private ephemeral OpenPGP signing operation.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="SysupdateEphemeralTestFixtureInfo-execution_requirements"></a>execution_requirements |  No-remote, no-cache action policy.    |
| <a id="SysupdateEphemeralTestFixtureInfo-keyring"></a>keyring |  Directory holding the certificate as import-pubring.gpg, for a guest's systemd keyring.    |
| <a id="SysupdateEphemeralTestFixtureInfo-public_key"></a>public_key |  Binary OpenPGP certificate of the ephemeral key.    |
| <a id="SysupdateEphemeralTestFixtureInfo-signatures"></a>signatures |  Detached signatures of the payloads' SHA256SUMS.    |


<a id="SysupdatePayloadInfo"></a>

## SysupdatePayloadInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "SysupdatePayloadInfo")

SysupdatePayloadInfo(<a href="#SysupdatePayloadInfo-directory">directory</a>, <a href="#SysupdatePayloadInfo-image_id">image_id</a>, <a href="#SysupdatePayloadInfo-image_version">image_version</a>, <a href="#SysupdatePayloadInfo-image_version_file">image_version_file</a>, <a href="#SysupdatePayloadInfo-signature">signature</a>)
</pre>

A directory of versioned update artifacts accepted by sysupdate_transfers definitions.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="SysupdatePayloadInfo-directory"></a>directory |  TreeArtifact with the root, verity and UKI artifacts plus SHA256SUMS.    |
| <a id="SysupdatePayloadInfo-image_id"></a>image_id |  os-release IMAGE_ID of the payload.    |
| <a id="SysupdatePayloadInfo-image_version"></a>image_version |  os-release IMAGE_VERSION string of the payload when known during analysis, or None.    |
| <a id="SysupdatePayloadInfo-image_version_file"></a>image_version_file |  File holding the payload's os-release IMAGE_VERSION when the image selected it through mkosi_image.image_version_file, or None. Exactly one of image_version and image_version_file is set.    |
| <a id="SysupdatePayloadInfo-signature"></a>signature |  Verified detached OpenPGP signature of the directory's SHA256SUMS, to publish as SHA256SUMS.gpg next to it, from sysupdate_import_signature; None for an unsigned payload.    |


<a id="SysupdateSigningRequestInfo"></a>

## SysupdateSigningRequestInfo

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "SysupdateSigningRequestInfo")

SysupdateSigningRequestInfo(<a href="#SysupdateSigningRequestInfo-format_version">format_version</a>, <a href="#SysupdateSigningRequestInfo-manifest">manifest</a>, <a href="#SysupdateSigningRequestInfo-payload">payload</a>, <a href="#SysupdateSigningRequestInfo-public_key">public_key</a>, <a href="#SysupdateSigningRequestInfo-request">request</a>)
</pre>

Request for an external signer to sign the SHA256SUMS manifest of a sysupdate payload.

**FIELDS**

| Name  | Description |
| :------------- | :------------- |
| <a id="SysupdateSigningRequestInfo-format_version"></a>format_version |  Request schema, mkosi-sysupdate-signing-request-v1.    |
| <a id="SysupdateSigningRequestInfo-manifest"></a>manifest |  Exact SHA256SUMS to sign.    |
| <a id="SysupdateSigningRequestInfo-payload"></a>payload |  SysupdatePayloadInfo of the unsigned payload.    |
| <a id="SysupdateSigningRequestInfo-public_key"></a>public_key |  Expected signer certificate as a binary OpenPGP transferable public key.    |
| <a id="SysupdateSigningRequestInfo-request"></a>request |  JSON request binding the manifest digest to the signer fingerprint.    |


<a id="debian_lock"></a>

## debian_lock

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "debian_lock")

debian_lock(<a href="#debian_lock-name">name</a>, <a href="#debian_lock-spec">spec</a>, <a href="#debian_lock-lock">lock</a>, <a href="#debian_lock-tags">tags</a>, <a href="#debian_lock-visibility">visibility</a>)
</pre>

Declares `<name>.update`, which regenerates `lock` from `spec`, and `<name>_test`, which fails when it is stale.

`bazel run :<name>.update` resolves `spec` with network access and rewrites `lock` in the source tree; further
arguments such as `--release` reach the generator. `<name>_test` runs offline and fails unless `lock` records
the SHA-256 of the normalized `spec`, so any change to the snapshot, components, or packages needs an update.


**PARAMETERS**


| Name  | Description | Default Value |
| :------------- | :------------- | :------------- |
| <a id="debian_lock-name"></a>name |  Prefix of the generated targets.   |  none |
| <a id="debian_lock-spec"></a>spec |  Debian package specification JSON in the main repository.   |  none |
| <a id="debian_lock-lock"></a>lock |  Lock JSON in the main repository; it need not exist before the first update.   |  none |
| <a id="debian_lock-tags"></a>tags |  Tags of both targets.   |  `[]` |
| <a id="debian_lock-visibility"></a>visibility |  Visibility of both targets.   |  `None` |


<a id="managed_python_test"></a>

## managed_python_test

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "managed_python_test")

managed_python_test(<a href="#managed_python_test-name">name</a>, <a href="#managed_python_test-src">src</a>, <a href="#managed_python_test-args">args</a>, <a href="#managed_python_test-data">data</a>, <a href="#managed_python_test-timeout">timeout</a>, <a href="#managed_python_test-tags">tags</a>)
</pre>

Tests the Python script src with rules_mkosi's managed interpreter, independent of the consumer's Python.

**PARAMETERS**


| Name  | Description | Default Value |
| :------------- | :------------- | :------------- |
| <a id="managed_python_test-name"></a>name |  Test name.   |  none |
| <a id="managed_python_test-src"></a>src |  Python script to run.   |  none |
| <a id="managed_python_test-args"></a>args |  Arguments passed to src.   |  `[]` |
| <a id="managed_python_test-data"></a>data |  Files available to the test at run time.   |  `[]` |
| <a id="managed_python_test-timeout"></a>timeout |  Bazel test timeout category.   |  `"moderate"` |
| <a id="managed_python_test-tags"></a>tags |  Test tags.   |  `[]` |


<a id="qemu_ovmf_boot_test"></a>

## qemu_ovmf_boot_test

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "qemu_ovmf_boot_test")

qemu_ovmf_boot_test(<a href="#qemu_ovmf_boot_test-name">name</a>, <a href="#qemu_ovmf_boot_test-image">image</a>, <a href="#qemu_ovmf_boot_test-secure_boot">secure_boot</a>, <a href="#qemu_ovmf_boot_test-timeout">timeout</a>, <a href="#qemu_ovmf_boot_test-tags">tags</a>, <a href="#qemu_ovmf_boot_test-kwargs">**kwargs</a>)
</pre>

Boots an image with OVMF and checks its serial lifecycle markers.

The test waits for readiness_marker on the serial console and then for the guest to power off by itself.
Multi-boot lifecycles, such as an A/B update followed by a reboot, set allow_reboot so that one QEMU process keeps
the image snapshot and the firmware variables across guest reboots and list their ordered checkpoints in
progress_markers; read_only_shares (virtio-9p) and http_shares (HTTP) expose update payloads to the guest.
Firmware, serial, QEMU, and boot-evidence logs are written to the test's undeclared outputs.


**PARAMETERS**


| Name  | Description | Default Value |
| :------------- | :------------- | :------------- |
| <a id="qemu_ovmf_boot_test-name"></a>name |  Name of the test. The configuration target is `<name>_config`.   |  none |
| <a id="qemu_ovmf_boot_test-image"></a>image |  mkosi_image to boot.   |  none |
| <a id="qemu_ovmf_boot_test-secure_boot"></a>secure_boot |  Boot Debian's Secure Boot capable OVMF in Setup Mode instead of the toolchain's OVMF; see docs/secure-boot.md.   |  `False` |
| <a id="qemu_ovmf_boot_test-timeout"></a>timeout |  Bazel timeout category of the test, passed to the configuration as test_timeout.   |  `"moderate"` |
| <a id="qemu_ovmf_boot_test-tags"></a>tags |  Tags of the test.   |  `[]` |
| <a id="qemu_ovmf_boot_test-kwargs"></a>kwargs |  Further attributes of qemu_ovmf_boot_config, such as readiness_marker.   |  none |


<a id="qemu_seabios_boot_test"></a>

## qemu_seabios_boot_test

<pre>
load("@rules_mkosi//mkosi:defs.bzl", "qemu_seabios_boot_test")

qemu_seabios_boot_test(<a href="#qemu_seabios_boot_test-name">name</a>, <a href="#qemu_seabios_boot_test-image">image</a>, <a href="#qemu_seabios_boot_test-timeout">timeout</a>, <a href="#qemu_seabios_boot_test-tags">tags</a>, <a href="#qemu_seabios_boot_test-kwargs">**kwargs</a>)
</pre>

Boots a BIOS image with the pinned SeaBIOS and checks its serial lifecycle markers.

The test waits for readiness_marker on the serial console and then for the guest to power off by itself.


**PARAMETERS**


| Name  | Description | Default Value |
| :------------- | :------------- | :------------- |
| <a id="qemu_seabios_boot_test-name"></a>name |  Name of the test. The configuration target is `<name>_config`.   |  none |
| <a id="qemu_seabios_boot_test-image"></a>image |  mkosi_image with `firmware = "bios"` to boot.   |  none |
| <a id="qemu_seabios_boot_test-timeout"></a>timeout |  Bazel timeout category of the test, passed to the configuration as test_timeout.   |  `"moderate"` |
| <a id="qemu_seabios_boot_test-tags"></a>tags |  Tags of the test.   |  `[]` |
| <a id="qemu_seabios_boot_test-kwargs"></a>kwargs |  Further attributes of qemu_seabios_boot_config, such as readiness_marker.   |  none |


