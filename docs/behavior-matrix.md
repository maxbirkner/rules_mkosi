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

<!-- behavior:BHV-IMAGE-FIRMWARE -->
`mkosi_image.firmware` defaults to `uefi`. Explicit `bios` is release-only,
requires an amd64 snapshot, selects GRUB i386-pc, disables the UEFI bootloader,
and rejects UKI and Secure Boot combinations.

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

<!-- behavior:BHV-IMAGE-IMMUTABLE -->
Unsigned UKI and hash-only dm-verity modes are release-only. Verity requires a
UKI so the root hash is carried by `.cmdline`; signed and unsupported modes
fail analysis. The normalized verity projection checks split artifact extents
against GPT, derives format geometry from the generated superblock, recomputes
the complete salted hash tree, and rejects truncation, mutation, and nonzero
padding. Verification uses constant-size buffers and one bounded on-disk
digest level at a time; format-1 digest slots are power-of-two padded. Inactive `_empty` A/B slots are excluded from the
projection.

<!-- behavior:BHV-IMAGE-SOURCES -->
`source_trees` accepts typed trees at unique normalized relative destinations,
preserves valid roles, and rejects traversal, aliases, collisions, and
untyped values.

<!-- behavior:BHV-IMAGE-ROOTFS-PAYLOADS -->
`rootfs_payloads` installs typed Bazel files and trees at normalized absolute
image paths, preserves declared executable and relative-symlink intent, and
rejects aliases, collisions, traversal, and unsafe links.

<!-- behavior:BHV-IMAGE-IDENTITY -->
`mkosi_image.image_id` and `image_version` expand Make variables, override
mkosi's `ImageId=`/`ImageVersion=`, and appear in `MkosiImageInfo` and the
build metadata. `image_version` requires `image_id` and accepts only letters,
digits, and `.`, a subset of the systemd-sysupdate version alphabet that keeps
`_`, `+`, and `-` free as separators in artifact names and boot counting.
`image_version_file` instead reads the version from a generated file at
execution time; it requires `image_id`, excludes `image_version`, and every
action that reads it applies the same rule to its content, which may end with
one newline. Its version reaches mkosi, the slot-label check, the build
metadata, and `sysupdate_payload` artifact names.

<!-- behavior:BHV-SYSUPDATE-TRANSFERS -->
`sysupdate_transfers` validates its image id, non-negative `boot_attempts`
(zero lists the counter-free UKI pattern first so that new UKIs are installed
without a boot counter), and at least two `instances`, and installs root,
verity, and UKI transfer definitions at a typed rootfs destination. Sources use
`PathRelativeTo=explicit`, partition targets take their UUID from `@u`, and
every transfer protects the running version.

<!-- behavior:BHV-TREE-SRC -->
`mkosi_config_tree.src` and `mkosi_source_tree.src` each resolve to exactly one
declared file or directory artifact and produce their typed provider.

<!-- behavior:BHV-TREE-EXECUTABLES -->
Both tree rules accept normalized `executable_paths`; staging preserves those
bits and rejects escaping paths.

<!-- behavior:BHV-BOOT-IMAGE -->
Both boot adapters require `MkosiImageInfo.raw_image`; the SeaBIOS adapter
additionally rejects images whose provider firmware tier is not `bios`.

<!-- behavior:BHV-BOOT-MARKERS -->
`readiness_marker` is nonempty and `shutdown_markers` contains only nonempty
markers; exact markers gate runtime readiness and clean shutdown.

<!-- behavior:BHV-BOOT-MACHINE -->
`machine_args` is passed before adapter-owned firmware arguments. OVMF owns
its flash drives; SeaBIOS owns the pinned ROM and debug-console capture.

<!-- behavior:BHV-BOOT-ACCELERATOR -->
`accelerator` on both boot adapters and `qemu_ovmf_smoke_test` defaults to
`auto`, which lists KVM before TCG so QEMU uses KVM when the test process can
open `/dev/kvm` for reading and writing and otherwise falls back to TCG.
`tcg` forces software emulation; every other value is rejected. The
accelerator QEMU actually selected, as reported by QMP `query-kvm`, is printed
in the test log and is the first line of the boot evidence.

<!-- behavior:BHV-BOOT-DEADLINES -->
`boot_timeout_seconds`, `qmp_initialization_timeout_seconds`, and
`shutdown_timeout_seconds` are positive, their sum plus cleanup fits the Bazel
timeout category, and the boundary equal to that category is accepted.

<!-- behavior:BHV-BOOT-DIAGNOSTICS -->
`diagnostic_bytes` is positive and bounds retained failure diagnostics.

<!-- behavior:BHV-BOOT-TIMEOUT -->
`test_timeout`/the public macro's `timeout` accepts `short`, `moderate`, and
`long`, propagates to the generated test, and rejects unsupported categories.

<!-- behavior:BHV-BOOT-LIFECYCLE -->
`progress_markers` must appear in order before readiness and contain only
nonempty markers; they cannot be combined with `expected_failure_marker`.
`allow_reboot` keeps one QEMU process, its writable image snapshot, and its
firmware variables across guest reboots. `read_only_shares` exposes directory
artifacts as read-only virtio-9p shares with unique 1-31 character mount tags,
resolving Bazel's symlinked tree artifacts to regular files.

<!-- behavior:BHV-MANAGED-PYTHON -->
`managed_python_test.src` requires one Python source, while `data` is optional;
the generated launcher uses the selected managed interpreter with isolated
user-site state and an empty child `PATH`.

## Provider contracts

<!-- behavior:BHV-SECURE-BOOT-OFFLINE -->
Secure Boot defaults to no key. Typed v1 providers separate deterministic
unsigned UKI creation, a digest-and-certificate-bound signing request, an
external Authenticode-signed PE, and verified signed assembly without filename
inference. Production keys never enter Bazel; an ephemeral test key exists
only inside one local, no-remote, no-cache action. Import validates the PE
certificate table, exact signer and SHA-256 signature, and byte equivalence
after only the defined Authenticode mutations. Signed external responses are
not reproducible.

<!-- behavior:BHV-SYSUPDATE-PAYLOAD -->
`sysupdate_payload` requires a versioned image with an unsigned UKI and
hash-only dm-verity, optionally substitutes an externally signed UKI whose
signing request names the image's unsigned UKI digest, and exposes
`SysupdatePayloadInfo`. It names the root and verity artifacts with the
partition UUIDs that systemd-repart derives from the root hash, rejects images
whose GPT UUIDs differ, writes `SHA256SUMS`, and leaves no partial output.

<!-- behavior:BHV-IMAGE-PROVIDER -->
`MkosiImageInfo` fixes `format_version`, exposes `raw_image`, `manifest`,
`partition_metadata`, `uki`, split root/hash/signature roles, normalized UKI
and verity metadata, and `build_metadata` as `File` or `None`, keeps
`image` as the exact raw-image alias, and projects every present artifact once
through `DefaultInfo`. Its `firmware` field exposes the selected tier directly,
and `image_id`/`image_version`/`image_version_file` expose the explicit image
identity or `None`.

<!-- behavior:BHV-TREE-PROVIDERS -->
`MkosiConfigTreeInfo` and `MkosiSourceTreeInfo` expose the declared `tree` and
its normalized `executable_paths`.

<!-- behavior:BHV-SNAPSHOT-PROVIDER -->
`DebianSnapshotInfo` exposes its format, distribution, release, codename,
architecture, components, timestamp/URL, lock digest, repository, metadata
files, package records, and package files from authenticated snapshot inputs.

<!-- behavior:BHV-SNAPSHOT-CONSUMER -->
`//mkosi/debian:generate_lock` resolves a consumer specification into a
deterministic multi-component lock from Release-verified indexes. The
`debian_tools.snapshot` tag turns that lock into a repository with a computed
lock digest and rejects duplicate or reserved repository names. Release images
built from it install packages from every component selected by
`Repositories=` and reject components absent from the snapshot.

<!-- behavior:BHV-DEBIAN-TOOLS-PROVIDER -->
`DebianToolsInfo` exposes distribution/release, authenticated tree/archive
identity, launcher and complete runfiles, static Python identity, provenance,
components, and required-component inventory.

<!-- behavior:BHV-MKOSI-TOOLCHAIN-PROVIDER -->
`MkosiToolchainInfo` exposes pinned mkosi provenance, script/runfiles,
`pefile`, and the selected compatible managed Python 3.14 runtime.

<!-- behavior:BHV-QEMU-TOOLCHAIN-PROVIDER -->
`MkosiQemuToolchainInfo` exposes pinned QEMU/system-data, OVMF files, and the
typed SeaBIOS ROM plus their immutable provenance.

<!-- behavior:BHV-BOOT-PROVIDER -->
`QemuOvmfBootConfigInfo` exposes validated timeout category, QMP/boot/shutdown
deadlines, and the fixed cleanup margin.

<!-- behavior:BHV-PARTITION-METADATA -->
Release `MkosiImageInfo.partition_metadata` is a provider-composed normalized
projection. It validates both GPT copies and their CRCs, requires identical
partition arrays, preserves stable sparse slot numbers, and omits variable GPT
disk and partition identities. Versioned dm-verity images instead require
exactly one populated root and verity slot labelled `<id>_<version>` and
`<id>_<version>_verity`, allow inactive `_empty` slots at least as large, and
record partition UUIDs, which are derived from the root hash. BIOS projections additionally require exactly
one BIOS boot partition of at least 1 MiB and record the firmware tier. Tracer
mode continues to expose `None`.

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

<!-- behavior:BHV-SYSUPDATE-LIFECYCLE -->
A versioned UEFI image updates itself in place with `systemd-sysupdate` from a
read-only payload into its `_empty` slots, boots the new release with its
verity root found through the UKI's `roothash=`, and blesses it once
`boot-complete.target` is reached. A release whose health check fails falls
back to the previous release after its boot attempts are exhausted.

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

<!-- behavior:BHV-CONSUMER-ISOLATION -->
The mkosi toolchain, `managed_python_test`, and the Debian launcher resolve
Python and the locked wheels for rules_mkosi's Python 3.14 line regardless of
the consumer's default `python_version`. The static Debian launcher and
namespace runner are built for the `bootstrap_platform` flag (default: the
current platform) with rules_python's `system_python` bootstrap, without
changing the platform of consumer targets. The maintained
`e2e/module_resolution/consumer_isolation` fixture combines a Python 3.13
default, `bootstrap_impl=script`, and a first-priority glibc C/C++ toolchain
that cannot link static executables.

<!-- behavior:BHV-ACTION-FAILURES -->
Executed failures preserve tool output and classify kernel capability,
toolchain, network, assembly, and VM boundaries with one actionable
remediation. SeaBIOS failures distinguish an absent boot sector, observable
GRUB/core failure, kernel/initrd/config guest failure, readiness timeout, and
post-readiness shutdown failure while retaining firmware, serial, and QEMU
logs. The successful no-cache BIOS qualification publishes bounded raw logs
and an actual stage-evidence excerpt through Bazel undeclared outputs.

<!-- behavior:BHV-STAGING-FAILURES -->
Staging rejects collisions, duplicate sources, absolute/traversing
destinations, escaping links, and invalid file roles before writing output.

<!-- behavior:BHV-SNAPSHOT-FAILURES -->
Snapshot materialization rejects bad OpenPGP signatures, mismatched Release
hashes, incomplete or misplaced component indexes, malformed/duplicate package
records, unsafe package paths, and content digest mismatches.

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
