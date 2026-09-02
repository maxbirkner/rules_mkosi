# Public behavior coverage

This catalog assigns stable IDs to maintained public behavior. The executable
matrix in `//mkosi/tests:behavior_matrix.tsv` maps every ID to tests by layer;
`//mkosi/tests:behavior_matrix_test` rejects missing, duplicate, malformed, or
unmapped IDs. A target may cover several closely related fields or validation
boundaries: the matrix measures contracts, not target count.

Root `analysis` and `artifact` tests exercise the ruleset itself. `consumer`
means the independently resolved `e2e/smoke` module. `runtime` means an
executed launcher, image, or VM lifecycle test. `module-resolution` identifies
a maintained nested-module fixture by its repository-owned `MODULE.bazel`
input. These labels are intentionally not encoded as Bazel tags.

## Rules and attributes

<!-- behavior:BHV-IMAGE-MODE -->
`mkosi_image.mode` defaults to networked, non-cacheable `tracer`, accepts
offline cacheable `release`, and rejects every other value.

<!-- behavior:BHV-IMAGE-CONFIG -->
Exactly one of `mkosi_image.config` and `config_tree` is required. `config`
resolves to one file; release mode requires a typed complete tree.

<!-- behavior:BHV-IMAGE-SNAPSHOT -->
`debian_snapshot` is required only in release mode and is rejected in tracer
mode.

<!-- behavior:BHV-IMAGE-SEED -->
`release_seed` is nonempty and required only in release mode; runtime validates
it against resolved `Seed=`.

<!-- behavior:BHV-IMAGE-EPOCH -->
`release_source_date_epoch` accepts zero and nonnegative values only for
release mode; runtime validates it against resolved `SourceDateEpoch=`.

<!-- behavior:BHV-IMAGE-SOURCES -->
`source_trees` accepts typed trees at unique normalized relative destinations,
preserves valid roles, and rejects traversal, aliases, collisions, and
untyped values.

<!-- behavior:BHV-IMAGE-ROOTFS-PAYLOADS -->
`rootfs_payloads` installs typed Bazel files and trees at normalized absolute
image paths, preserves declared executable and relative-symlink intent, and
rejects aliases, collisions, traversal, and unsafe links.

<!-- behavior:BHV-TREE-SRC -->
`mkosi_config_tree.src` and `mkosi_source_tree.src` each resolve to exactly one
declared file or directory artifact and produce their typed provider.

<!-- behavior:BHV-TREE-EXECUTABLES -->
Both tree rules accept normalized `executable_paths`; staging preserves those
bits and rejects escaping paths.

<!-- behavior:BHV-BOOT-IMAGE -->
`qemu_ovmf_boot_config.image` requires `MkosiImageInfo.raw_image`.

<!-- behavior:BHV-BOOT-MARKERS -->
`readiness_marker` is nonempty and `shutdown_markers` contains only nonempty
markers; exact markers gate runtime readiness and clean shutdown.

<!-- behavior:BHV-BOOT-MACHINE -->
`machine_args` is passed before adapter-owned OVMF flash arguments, including
the empty-list boundary.

<!-- behavior:BHV-BOOT-DEADLINES -->
`boot_timeout_seconds`, `qmp_initialization_timeout_seconds`, and
`shutdown_timeout_seconds` are positive, their sum plus cleanup fits the Bazel
timeout category, and the boundary equal to that category is accepted.

<!-- behavior:BHV-BOOT-DIAGNOSTICS -->
`diagnostic_bytes` is positive and bounds retained failure diagnostics.

<!-- behavior:BHV-BOOT-TIMEOUT -->
`test_timeout`/the public macro's `timeout` accepts `short`, `moderate`, and
`long`, propagates to the generated test, and rejects unsupported categories.

<!-- behavior:BHV-MANAGED-PYTHON -->
`managed_python_test.src` requires one Python source, while `data` is optional;
the generated launcher uses the selected managed interpreter with isolated
user-site state and an empty child `PATH`.

## Provider contracts

<!-- behavior:BHV-IMAGE-PROVIDER -->
`MkosiImageInfo` fixes `format_version`, exposes `raw_image`, `manifest`,
`partition_metadata`, `uki`, and `build_metadata` as `File` or `None`, keeps
`image` as the exact raw-image alias, and projects every present artifact once
through `DefaultInfo`.

<!-- behavior:BHV-TREE-PROVIDERS -->
`MkosiConfigTreeInfo` and `MkosiSourceTreeInfo` expose the declared `tree` and
its normalized `executable_paths`.

<!-- behavior:BHV-SNAPSHOT-PROVIDER -->
`DebianSnapshotInfo` exposes its format, distribution, release, codename,
architecture, timestamp/URL, lock digest, repository, metadata files, package
records, and package files from authenticated snapshot inputs.

<!-- behavior:BHV-DEBIAN-TOOLS-PROVIDER -->
`DebianToolsInfo` exposes distribution/release, authenticated tree/archive
identity, launcher and complete runfiles, static Python identity, provenance,
components, and required-component inventory.

<!-- behavior:BHV-MKOSI-TOOLCHAIN-PROVIDER -->
`MkosiToolchainInfo` exposes pinned mkosi provenance, script/runfiles,
`pefile`, and the selected compatible managed Python 3.14 runtime.

<!-- behavior:BHV-QEMU-TOOLCHAIN-PROVIDER -->
`MkosiQemuToolchainInfo` exposes pinned QEMU/system-data and OVMF files plus
their immutable provenance.

<!-- behavior:BHV-BOOT-PROVIDER -->
`QemuOvmfBootConfigInfo` exposes validated timeout category, QMP/boot/shutdown
deadlines, and the fixed cleanup margin.

<!-- behavior:BHV-PARTITION-METADATA -->
Release `MkosiImageInfo.partition_metadata` is a provider-composed normalized
projection. It validates both GPT copies and their CRCs, requires identical
partition arrays, preserves stable sparse slot numbers, and omits variable GPT
disk and partition identities. Tracer mode continues to expose `None`.

<!-- behavior:BHV-REPRODUCIBILITY-PROJECTION -->
`mkosi_reproducibility_manifest` selects raw image, build metadata, and
partition metadata through `MkosiImageInfo`. Its stable normalized projection
content-addresses immutable artifacts and embeds both normalized metadata
documents without inferring provider roles from filenames.

<!-- behavior:BHV-CANONICAL-DIGEST -->
The reproducibility manifest's canonical whole-image digest covers every image
byte while narrowly normalizing GPT disk/partition identity and the checksums
that necessarily depend on those identities. Partition geometry, type, label,
attributes, and payload changes remain observable.

<!-- behavior:BHV-REPRODUCIBILITY-INDEPENDENCE -->
Release reproducibility executes two real image and manifest action graphs in
distinct clean Bazel output roots with cache reuse disabled, proves both
actions executed, and compares their projections. A mismatch reports that
immutable hashes or normalized manifests differ.

## Actions, toolchains, validation, and expected failures

<!-- behavior:BHV-IMAGE-ACTIONS -->
Image analysis registers deterministic staging when needed, one `MkosiImage`
action, and normalized metadata; executed artifacts retain staged content and
forced raw/disk/uncompressed output semantics.

<!-- behavior:BHV-RELEASE-RUNTIME -->
Release execution consumes only the authenticated snapshot, blocks networking,
removes persistent APT sources, rejects host-dependent configuration, and
emits reproducibility and snapshot metadata.

<!-- behavior:BHV-TRACER-RUNTIME -->
Tracer execution uses the pinned mkosi and Debian tools with explicit network,
local-execution, and no-cache requirements and produces a structurally valid
raw image.

<!-- behavior:BHV-TOOLCHAIN-PATHS -->
Image, managed-Python, Debian tools, QEMU, firmware, and consumer-overridden
Python paths come from registered toolchains with complete runfiles rather
than ambient host executables.

<!-- behavior:BHV-EXTENSION-VALIDATION -->
The module extension selects the default or one supported pinned version,
honors one root override, and rejects unsupported, conflicting, multiple-name,
or dependency-owned-name requests. The dependency-owned-name rejection is the
maintained `e2e/module_resolution/nonroot_name` fixture.

<!-- behavior:BHV-ACTION-FAILURES -->
Executed failures preserve tool output and classify kernel capability,
toolchain, network, assembly, and VM boundaries with one actionable
remediation.

<!-- behavior:BHV-STAGING-FAILURES -->
Staging rejects collisions, duplicate sources, absolute/traversing
destinations, escaping links, and invalid file roles before writing output.

<!-- behavior:BHV-SNAPSHOT-FAILURES -->
Snapshot materialization rejects bad OpenPGP signatures, mismatched Release
hashes, malformed/duplicate package records, unsafe package paths, and content
digest mismatches.

## Why line coverage is not a target

Bazel coverage instruments languages built by rules, not Starlark evaluated
during loading and analysis. Consequently this repository's `.bzl` behavior
does not produce meaningful Starlark LCOV. Coveragemap consumes LCOV and could
display `.bzl` paths, but without instrumented Starlark input it would only
visualize absence, not coverage. Empty LCOV, synthetic counters, workflow
syntax checks, and target counts are therefore explicitly excluded. This
behavioral catalog remains the maintained coverage contract until Bazel
provides Starlark coverage or relevant logic moves into an instrumentable
helper. Exact supported-version evidence and the periodic reevaluation
procedure are recorded in [Starlark coverage status](starlark-coverage.md).
