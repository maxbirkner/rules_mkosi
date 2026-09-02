"""Implementation of the public mkosi_image rule."""

load("//mkosi/private:debian_snapshot.bzl", "DebianSnapshotInfo")

MkosiImageInfo = provider(
    doc = """Stable output contract for mkosi_image.

Consumers select artifacts through these fields, never by inspecting
DefaultInfo filenames. Every artifact field is either a File or None. The
raw_image and build_metadata fields are present for every currently supported
mkosi_image target; release images also provide partition_metadata. DefaultInfo
contains every non-None artifact field once.
The image field is a compatibility alias for raw_image.
""",
    fields = {
        "format_version": "Stable MkosiImageInfo contract version, currently mkosi-image-v1.",
        "raw_image": "The raw disk image File, or None when an output mode does not produce one.",
        "manifest": "The mkosi manifest File, or None when manifest generation is disabled.",
        "partition_metadata": "Normalized, validated GPT partition metadata File for release images, or None.",
        "uki": "The Unified Kernel Image File, or None when no UKI is generated.",
        "build_metadata": "Normalized JSON build-metadata File describing this contract's output modes.",
        "firmware": "Selected firmware tier: uefi or bios.",
        "image": "Deprecated compatibility alias for raw_image; use raw_image in new consumers.",
    },
)

MkosiConfigTreeInfo = provider(
    doc = "Explicitly typed mkosi configuration tree.",
    fields = {
        "tree": "The declared configuration directory artifact.",
        "executable_paths": "Relative paths that must retain executable mode.",
        "is_generated": "Whether the tree is a generated TreeArtifact.",
    },
)

MkosiSourceTreeInfo = provider(
    doc = "Explicitly typed mkosi BuildSources tree.",
    fields = {
        "tree": "The declared source directory artifact.",
        "executable_paths": "Relative paths that must retain executable mode.",
        "is_generated": "Whether the tree is a generated TreeArtifact.",
    },
)

MkosiRootfsPayloadInfo = provider(
    doc = "Typed file or tree installed into an explicit image-root destination.",
    fields = {
        "artifact": "The declared file or directory artifact.",
        "destination": "Normalized absolute destination inside the image root.",
        "executable_paths": "Relative tree paths, or an empty string for a file, that must be executable.",
        "is_tree": "Whether artifact is a directory whose contents are installed at destination.",
        "is_generated": "Whether artifact is generated rather than a source artifact.",
    },
)

def _tree_target_impl(ctx, info):
    files = ctx.files.src
    if len(files) != 1:
        fail("{} must resolve to exactly one directory artifact".format(ctx.label))
    return [
        DefaultInfo(files = depset(files)),
        info(
            tree = files[0],
            executable_paths = ctx.attr.executable_paths,
            is_generated = not files[0].is_source,
        ),
    ]

mkosi_config_tree = rule(
    implementation = lambda ctx: _tree_target_impl(ctx, MkosiConfigTreeInfo),
    attrs = {
        "src": attr.label(
            mandatory = True,
            allow_files = True,
            doc = "A declared configuration directory, including mkosi.conf.",
        ),
        "executable_paths": attr.string_list(
            doc = "Relative configuration-tree paths that must be executable.",
        ),
    },
    doc = "Marks a label as an mkosi configuration tree.",
)

mkosi_source_tree = rule(
    implementation = lambda ctx: _tree_target_impl(ctx, MkosiSourceTreeInfo),
    attrs = {
        "src": attr.label(
            mandatory = True,
            allow_files = True,
            doc = "A declared directory mounted for mkosi BuildSources.",
        ),
        "executable_paths": attr.string_list(
            doc = "Relative source-tree paths that must be executable.",
        ),
    },
    doc = "Marks a label as an mkosi BuildSources tree.",
)

def _rootfs_payload_impl(ctx):
    artifact = _single_input(ctx.attr.src, "src")
    destination = _normalise_image_destination(ctx.attr.destination)
    is_tree = artifact.is_directory
    executable_paths = ctx.attr.executable_paths
    if not is_tree and executable_paths not in ([], [""]):
        fail("file rootfs payload executable_paths must be empty or ['']")
    for path in executable_paths:
        if path:
            _normalise_destination(path, "executable_paths")
    return [
        DefaultInfo(files = depset([artifact])),
        MkosiRootfsPayloadInfo(
            artifact = artifact,
            destination = destination,
            executable_paths = executable_paths,
            is_generated = not artifact.is_source,
            is_tree = is_tree,
        ),
    ]

mkosi_rootfs_payload = rule(
    implementation = _rootfs_payload_impl,
    attrs = {
        "src": attr.label(
            mandatory = True,
            allow_files = True,
            doc = "A single source or generated Bazel file or directory artifact.",
        ),
        "destination": attr.string(
            mandatory = True,
            doc = "Normalized absolute path at which to install the file or tree.",
        ),
        "executable_paths": attr.string_list(
            doc = "Relative file paths to make executable; use [''] for a file payload.",
        ),
    },
    doc = "Declares a deterministic root-owned payload for installation into an image.",
)

def _mkosi_reproducibility_manifest_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    if image.raw_image == None or image.build_metadata == None or image.partition_metadata == None:
        fail("image must provide raw_image, build_metadata, and partition_metadata")

    output = ctx.actions.declare_file(ctx.label.name + ".reproducibility.json")
    mkosi = ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi
    args = ctx.actions.args()
    args.add(ctx.file._projector.path)
    args.add("--raw-image")
    args.add(image.raw_image.path)
    args.add("--build-metadata")
    args.add(image.build_metadata.path)
    args.add("--partition-metadata")
    args.add(image.partition_metadata.path)
    args.add("--output")
    args.add(output.path)
    ctx.actions.run(
        executable = mkosi.python,
        arguments = [args],
        inputs = depset(
            [image.raw_image, image.build_metadata, image.partition_metadata, ctx.file._partition_projector, ctx.file._projector],
            transitive = [mkosi.python_runtime_files],
        ),
        tools = [mkosi.python_files_to_run],
        outputs = [output],
        mnemonic = "MkosiReproducibilityManifest",
        progress_message = "Projecting reproducibility manifest for %{label}",
        env = {
            "PATH": "",
            "PYTHONNOUSERSITE": "1",
        },
    )
    return [DefaultInfo(files = depset([output]))]

mkosi_reproducibility_manifest = rule(
    implementation = _mkosi_reproducibility_manifest_impl,
    attrs = {
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
            doc = "Release-mode image whose immutable outputs are projected.",
        ),
        "_projector": attr.label(
            cfg = "exec",
            default = "//mkosi/private:reproducibility_manifest.py",
            allow_single_file = True,
        ),
        "_partition_projector": attr.label(
            cfg = "exec",
            default = "//mkosi/private:partition_metadata.py",
            allow_single_file = True,
        ),
    },
    doc = "Produces a normalized JSON manifest of an image's immutable content hashes.",
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)

def _normalise_destination(destination, attribute):
    """Validates a path inside the staged mkosi directory."""
    if not destination:
        fail("{} entries must have a non-empty relative destination".format(attribute))
    if destination.startswith("/") or "\\" in destination:
        fail("{} destination '{}' must be relative".format(attribute, destination))

    parts = destination.split("/")
    if any([part in ("", ".", "..") for part in parts]):
        fail("{} destination '{}' is not a normalized relative path".format(attribute, destination))
    return "/".join(parts)

def _normalise_image_destination(destination):
    if not destination.startswith("/") or destination == "/":
        fail("rootfs payload destination '{}' must be an absolute path below /".format(destination))
    return "/" + _normalise_destination(destination[1:], "rootfs payload")

def _single_input(target, attribute):
    files = target.files.to_list()
    if len(files) != 1:
        fail("{} must resolve to exactly one single file or directory, got {}".format(attribute, len(files)))
    return files[0]

def _image_default_info(
        raw_image,
        manifest,
        partition_metadata,
        uki,
        build_metadata):
    """Returns the DefaultInfo projection of the MkosiImageInfo artifacts."""
    return DefaultInfo(
        files = depset([
            artifact
            for artifact in [
                raw_image,
                manifest,
                partition_metadata,
                uki,
                build_metadata,
            ]
            if artifact != None
        ]),
    )

def _stage_inputs(ctx, config, config_is_directory, source_trees, rootfs_payloads):
    staging = ctx.actions.declare_directory(ctx.label.name + ".mkosi")
    manifest = ctx.actions.declare_file(ctx.label.name + ".mkosi.manifest")
    mappings = []

    if config_is_directory:
        mappings.append((
            config.path,
            ".",
            "generated-tree" if ctx.attr.config_tree[MkosiConfigTreeInfo].is_generated else "tree",
        ))
    else:
        mappings.append((config.path, config.basename, "file"))

    for destination in sorted(source_trees):
        mappings.append((
            source_trees[destination].tree.path,
            destination,
            "generated-tree" if source_trees[destination].is_generated else "tree",
        ))
    for payload in rootfs_payloads:
        mappings.append((
            payload.artifact.path,
            "mkosi.extra" + payload.destination,
            (
                "generated-tree" if payload.is_tree and payload.is_generated else "tree" if payload.is_tree else "file"
            ),
        ))

    executable_paths = []
    if config_is_directory:
        executable_paths += ctx.attr.config_tree[MkosiConfigTreeInfo].executable_paths
    for destination in sorted(source_trees):
        executable_paths += [
            destination + "/" + path
            for path in source_trees[destination].executable_paths
        ]
    for payload in rootfs_payloads:
        prefix = "mkosi.extra" + payload.destination
        executable_paths += [
            prefix + (("/" + path) if path else "")
            for path in payload.executable_paths
        ]
    executable_paths = [
        _normalise_destination(path, "executable_paths")
        for path in executable_paths
    ]

    destinations = {}
    sources = {}
    for source, destination, role in mappings:
        if destination == ".":
            destination = ""
        elif destination:
            destination = _normalise_destination(destination, "staged inputs")

        if destination in destinations:
            fail("duplicate staged destination '{}' from {} and {}".format(
                destination or ".",
                destinations[destination],
                source,
            ))
        destinations[destination] = source
        if source in sources:
            fail("duplicate staged source '{}' at '{}' and '{}'".format(
                source,
                sources[source],
                destination or ".",
            ))
        sources[source] = destination

        # A source tree rooted below another source tree would have ambiguous
        # ownership even when the two labels happen to contain disjoint files.
        for other in destinations:
            if other == destination or not other:
                continue
            if destination.startswith(other + "/") or other.startswith(destination + "/"):
                fail("colliding staged destinations '{}' and '{}'".format(destination, other))

    stage_args = ctx.actions.args()
    stage_args.add(ctx.file._stage_script.path)
    stage_args.add("--output")
    stage_args.add(staging.path)
    stage_args.add("--manifest")
    stage_args.add(manifest.path)
    for source, destination, role in mappings:
        stage_args.add("--mapping")
        stage_args.add(source)
        stage_args.add(destination)
        stage_args.add(role)
    for path in executable_paths:
        stage_args.add("--executable")
        stage_args.add(path)

    mkosi = ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi
    ctx.actions.run(
        executable = mkosi.python,
        arguments = [stage_args],
        inputs = depset(
            [config, ctx.file._stage_script] +
            [source_trees[destination].tree for destination in sorted(source_trees)] +
            [payload.artifact for payload in rootfs_payloads],
            transitive = [mkosi.python_runtime_files],
        ),
        tools = [mkosi.python_files_to_run],
        outputs = [staging, manifest],
        mnemonic = "MkosiStageInputs",
        progress_message = "Staging mkosi inputs for %{label}",
        env = {
            "PATH": "",
            "PYTHONNOUSERSITE": "1",
        },
    )
    return struct(tree = staging, manifest = manifest)

def _execution_requirements(release_mode):
    if release_mode:
        return {
            "block-network": "1",
            "no-remote-exec": "1",
        }
    return {
        "no-cache": "1",
        "no-remote-exec": "1",
        "requires-network": "1",
    }

def _mkosi_image_impl(ctx):
    mkosi = ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi
    debian_tools = ctx.toolchains["//mkosi/toolchain:debian_tools_toolchain_type"].debian_tools
    release_mode = ctx.attr.mode == "release"
    firmware = ctx.attr.firmware
    if ctx.attr.mode not in ("tracer", "release"):
        fail("mode must be either 'tracer' or 'release'")
    if firmware not in ("uefi", "bios"):
        fail("firmware must be either 'uefi' or 'bios'")
    if firmware == "bios" and not release_mode:
        fail("bios firmware requires release mode")
    if release_mode and not ctx.attr.debian_snapshot:
        fail("release mode requires debian_snapshot")
    if not release_mode and ctx.attr.debian_snapshot:
        fail("debian_snapshot is only supported in release mode")
    if release_mode and not ctx.attr.release_seed:
        fail("release mode requires release_seed")
    if release_mode and ctx.attr.release_source_date_epoch < 0:
        fail("release mode requires a non-negative release_source_date_epoch")
    if not release_mode and (
        ctx.attr.release_seed or
        ctx.attr.release_source_date_epoch >= 0
    ):
        fail("release_seed and release_source_date_epoch are only supported in release mode")
    if ctx.attr.config and ctx.attr.config_tree:
        fail("set exactly one of config and config_tree")
    if not ctx.attr.config and not ctx.attr.config_tree:
        fail("one of config or config_tree is required")

    config_is_directory = bool(ctx.attr.config_tree)
    if release_mode and not config_is_directory:
        fail("release mode requires config_tree so every configuration path is declared")
    config = (
        ctx.attr.config_tree[MkosiConfigTreeInfo].tree if config_is_directory else _single_input(ctx.attr.config, "config")
    )
    source_trees = {}
    for destination, target in ctx.attr.source_trees.items():
        source_trees[destination] = target[MkosiSourceTreeInfo]
    rootfs_payloads = [
        target[MkosiRootfsPayloadInfo]
        for target in ctx.attr.rootfs_payloads
    ]

    staging = None
    if config_is_directory or source_trees or rootfs_payloads:
        staging = _stage_inputs(ctx, config, config_is_directory, source_trees, rootfs_payloads)

    image = ctx.actions.declare_file(ctx.label.name + ".raw")
    partition_metadata = (
        ctx.actions.declare_file(ctx.label.name + ".partitions.json") if release_mode else None
    )
    build_metadata = ctx.actions.declare_file(
        ctx.label.name + ".mkosi-image-info.json",
    )
    bios_partition_definition = None
    if firmware == "bios":
        bios_partition_definition = ctx.actions.declare_directory(
            ctx.label.name + ".bios-repart",
        )
        ctx.actions.run(
            executable = mkosi.python,
            arguments = [ctx.file._write_bios_repart.path, bios_partition_definition.path],
            inputs = depset(
                [ctx.file._write_bios_repart],
                transitive = [mkosi.python_runtime_files],
            ),
            tools = [mkosi.python_files_to_run],
            outputs = [bios_partition_definition],
            mnemonic = "MkosiBiosRepart",
            env = {
                "PATH": "",
                "PYTHONNOUSERSITE": "1",
            },
        )
    output_name = image.basename[:-len(".raw")]
    workspace = image.dirname + "/." + ctx.label.name + "-mkosi"
    mkosi_root = mkosi.script.path[:-len("/mkosi/__main__.py")]
    pefile_root = mkosi.pefile.path[:-len("/pefile.py")]

    arguments = ctx.actions.args()
    arguments.add(ctx.file._run_script.path)
    arguments.add(mkosi.script.path)
    arguments.add("--debian-tools-archive")
    arguments.add(debian_tools.tree.path)
    arguments.add("--debian-tools-extractor")
    arguments.add(debian_tools.extractor.path)
    arguments.add("--debian-tools-sha256")
    arguments.add(debian_tools.archive_sha256)
    arguments.add("--kernel-preflight")
    arguments.add(ctx.executable._kernel_preflight.path)
    if release_mode:
        snapshot = ctx.attr.debian_snapshot[DebianSnapshotInfo]
        if firmware == "bios" and snapshot.architecture != "amd64":
            fail("bios firmware requires an amd64 Debian snapshot")
        arguments.add("--debian-snapshot-repository")
        arguments.add(snapshot.repository.path)
        arguments.add("--release-seed")
        arguments.add(ctx.attr.release_seed)
        arguments.add("--release-source-date-epoch")
        arguments.add(ctx.attr.release_source_date_epoch)
        arguments.add("--release-distribution")
        arguments.add(snapshot.distribution)
        arguments.add("--release-codename")
        arguments.add(snapshot.codename)
        arguments.add("--release-snapshot")
        arguments.add(snapshot.snapshot)
        arguments.add("--release-firmware")
        arguments.add(firmware)
    if config_is_directory:
        for path in ctx.attr.config_tree[MkosiConfigTreeInfo].executable_paths:
            arguments.add("--executable-path")
            arguments.add(path)
    for destination in sorted(source_trees):
        for path in source_trees[destination].executable_paths:
            arguments.add("--executable-path")
            arguments.add(destination + "/" + path)
    for payload in rootfs_payloads:
        prefix = "mkosi.extra" + payload.destination
        for path in payload.executable_paths:
            arguments.add("--executable-path")
            arguments.add(prefix + (("/" + path) if path else ""))
    if staging:
        arguments.add("--staging-manifest")
        arguments.add(staging.manifest.path)
    arguments.add("--")
    if staging:
        arguments.add("-C")
        arguments.add(staging.tree.path)
        if not config_is_directory and config.basename != "mkosi.conf":
            arguments.add("-I")
            arguments.add(staging.tree.path + "/" + config.basename)
    else:
        arguments.add("-I")
        arguments.add(config.path)
    arguments.add("--tools-tree")
    arguments.add(workspace + "/debian-tools")
    arguments.add("--extra-search-path")
    arguments.add(pefile_root)
    arguments.add("--format=disk")
    arguments.add("--output-extension=raw")
    arguments.add("--compress-output=none")
    arguments.add("--split-artifacts=")
    if firmware == "bios":
        arguments.add("--architecture=x86-64")
        arguments.add("--bootable=yes")
        arguments.add("--bootloader=none")
        arguments.add("--bios-bootloader=grub")
        arguments.add("--initrd=")
        for package in ("grub-pc-bin", "grub-common", "grub2-common"):
            arguments.add("--package=" + package)
        arguments.add("--repart-directory")
        arguments.add(bios_partition_definition.path)
    arguments.add("--output-directory")
    arguments.add(image.dirname)
    arguments.add("--output")
    arguments.add(output_name)
    arguments.add("--workspace-directory")
    arguments.add(workspace)
    arguments.add("--cache-directory")
    arguments.add(workspace + "/cache")
    arguments.add("--package-cache-directory")
    arguments.add(workspace + "/package-cache")
    arguments.add("--build-directory")
    arguments.add(workspace + "/build")
    if not source_trees:
        arguments.add("--build-sources=")
    arguments.add("--no-pager")
    arguments.add("build")

    environment = {
        "PATH": "",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": mkosi_root + ":" + pefile_root,
    }
    if release_mode:
        snapshot = ctx.attr.debian_snapshot[DebianSnapshotInfo]
        environment.update({
            "MKOSI_HOST_DISTRIBUTION": snapshot.distribution,
            "MKOSI_HOST_RELEASE": snapshot.codename,
            "SOURCE_DATE_EPOCH": str(ctx.attr.release_source_date_epoch),
        })

    ctx.actions.run(
        executable = mkosi.python,
        arguments = [arguments],
        inputs = depset(
            [config, mkosi.script, ctx.file._run_script, ctx.file._diagnostics, ctx.executable._kernel_preflight, mkosi.pefile, debian_tools.tree, debian_tools.extractor] +
            ([bios_partition_definition] if bios_partition_definition else []) +
            (
                [ctx.attr.debian_snapshot[DebianSnapshotInfo].repository] if release_mode else []
            ) +
            ([staging.tree, staging.manifest] if staging else []),
            transitive = [mkosi.runfiles_files, mkosi.python_runtime_files],
        ),
        tools = [
            mkosi.python_files_to_run,
            ctx.attr._kernel_preflight[DefaultInfo].files_to_run,
        ],
        outputs = [image],
        env = environment,
        execution_requirements = _execution_requirements(release_mode),
        mnemonic = "MkosiImage",
        progress_message = "Building mkosi image %{label}",
    )

    if release_mode:
        partition_arguments = ctx.actions.args()
        partition_arguments.add(ctx.file._partition_metadata.path)
        partition_arguments.add("--image")
        partition_arguments.add(image.path)
        partition_arguments.add("--output")
        partition_arguments.add(partition_metadata.path)
        partition_arguments.add("--firmware")
        partition_arguments.add(firmware)
        ctx.actions.run(
            executable = mkosi.python,
            arguments = [partition_arguments],
            inputs = depset(
                [ctx.file._partition_metadata, image],
                transitive = [mkosi.python_runtime_files],
            ),
            tools = [
                mkosi.python_files_to_run,
            ],
            outputs = [partition_metadata],
            env = {
                "PATH": "",
                "PYTHONNOUSERSITE": "1",
            },
            execution_requirements = _execution_requirements(True),
            mnemonic = "MkosiPartitionMetadata",
            progress_message = "Projecting GPT metadata for %{label}",
        )

    # This projection deliberately records output roles and normalized mkosi
    # settings rather than deriving meaning from output filenames or binaries.
    metadata = {
        "artifacts": {
            "build_metadata": True,
            "manifest": False,
            "partition_metadata": release_mode,
            "raw_image": True,
            "uki": False,
        },
        "format_version": "mkosi-image-build-metadata-v2",
        "mkosi": {
            "compression": "none",
            "format": "disk",
            "split_artifacts": False,
            "version": mkosi.version,
        },
        "mode": ctx.attr.mode,
        "firmware": firmware,
    }
    if release_mode:
        snapshot = ctx.attr.debian_snapshot[DebianSnapshotInfo]
        metadata["debian_snapshot"] = {
            "architecture": snapshot.architecture,
            "codename": snapshot.codename,
            "format_version": snapshot.format_version,
            "lock_sha256": snapshot.lock_sha256,
            "snapshot": snapshot.snapshot,
            "snapshot_url": snapshot.snapshot_url,
        }
        metadata["reproducibility"] = {
            "seed": ctx.attr.release_seed,
            "source_date_epoch": ctx.attr.release_source_date_epoch,
        }

    ctx.actions.write(
        output = build_metadata,
        content = json.encode(metadata) + "\n",
    )

    return [
        _image_default_info(
            raw_image = image,
            manifest = None,
            partition_metadata = partition_metadata,
            uki = None,
            build_metadata = build_metadata,
        ),
        MkosiImageInfo(
            format_version = "mkosi-image-v1",
            raw_image = image,
            manifest = None,
            partition_metadata = partition_metadata,
            uki = None,
            build_metadata = build_metadata,
            firmware = firmware,
            image = image,
        ),
    ]

mkosi_image = rule(
    implementation = _mkosi_image_impl,
    attrs = {
        "mode": attr.string(
            default = "tracer",
            doc = """Image build mode: "tracer" permits network-backed package acquisition and is non-cacheable; "release" uses only debian_snapshot with network blocked and may use Bazel caches.

Release mode remains local-execution-only until its Linux execution platform is qualified for remote execution.
""",
        ),
        "firmware": attr.string(
            default = "uefi",
            doc = """Firmware tier. "uefi" preserves the default behavior; "bios" is an explicitly selected x86-64 release-only compatibility tier using GRUB i386-pc and a GPT BIOS boot partition.""",
        ),
        "debian_snapshot": attr.label(
            providers = [DebianSnapshotInfo],
            doc = "Authenticated Debian snapshot repository required by release mode.",
        ),
        "release_seed": attr.string(
            doc = "Required fixed UUID that must match the release configuration's resolved Seed=.",
        ),
        "release_source_date_epoch": attr.int(
            default = -1,
            doc = "Required non-negative value that must match the release configuration's resolved SourceDateEpoch=.",
        ),
        "config": attr.label(
            allow_files = True,
            doc = "A single mkosi configuration file (legacy compatibility API).",
        ),
        "config_tree": attr.label(
            providers = [MkosiConfigTreeInfo],
            doc = "An explicitly typed complete mkosi configuration tree.",
        ),
        "source_trees": attr.string_keyed_label_dict(
            allow_files = True,
            providers = [MkosiSourceTreeInfo],
            doc = """Source directories staged at the relative paths used by BuildSources.

The keys are normalized relative paths such as "src". Each value must resolve
to an explicitly typed directory tree. The directory contents, rather than
its label basename, are copied to that key.
""",
        ),
        "rootfs_payloads": attr.label_list(
            providers = [MkosiRootfsPayloadInfo],
            doc = "Typed payloads installed at explicit image-root destinations through mkosi.extra.",
        ),
        "_stage_script": attr.label(
            cfg = "exec",
            default = "//mkosi/private:stage_inputs.py",
            allow_single_file = True,
        ),
        "_write_bios_repart": attr.label(
            cfg = "exec",
            default = "//mkosi/private:write_bios_repart.py",
            allow_single_file = True,
        ),
        "_run_script": attr.label(
            cfg = "exec",
            default = "//mkosi/private:run_mkosi.py",
            allow_single_file = True,
        ),
        "_kernel_preflight": attr.label(
            cfg = "exec",
            default = "//mkosi/private:kernel_preflight",
            executable = True,
        ),
        "_partition_metadata": attr.label(
            cfg = "exec",
            default = "//mkosi/private:partition_metadata.py",
            allow_single_file = True,
        ),
        "_diagnostics": attr.label(
            cfg = "exec",
            default = "//mkosi/private:diagnostics.py",
            allow_single_file = True,
        ),
    },
    doc = """Builds a raw disk image using the pinned mkosi and Debian toolchains.

The default tracer mode downloads target Debian packages over the network and
is intentionally non-cacheable. Release mode requires an authenticated
debian_snapshot, materializes it as mkosi's only local APT mirror, blocks
network access, and permits Bazel cache reuse. Both modes require the Linux
namespace and mount capabilities documented by the host-kernel contract;
release mode does not claim remote-execution portability. MkosiImageInfo.raw_image
and MkosiImageInfo.build_metadata are present; release images also provide
validated normalized partition_metadata, while manifest and uki are None.
DefaultInfo includes every provided artifact, so
consumers that need a particular artifact must select its MkosiImageInfo field.
""",
    provides = [MkosiImageInfo],
    toolchains = [
        "//mkosi/toolchain:toolchain_type",
        "//mkosi/toolchain:debian_tools_toolchain_type",
    ],
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
)
