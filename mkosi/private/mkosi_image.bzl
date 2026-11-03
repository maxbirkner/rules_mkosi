"""Rules and providers that build mkosi images."""

load("//mkosi/private:debian_snapshot.bzl", "DebianSnapshotInfo")
load("//mkosi/private:image_identity.bzl", "validate_image_id", "validate_image_version", "validate_slot_labels")
load(
    ":image_metadata.bzl",
    "IMAGE_METADATA_ATTRS",
    "project_partition_metadata",
    "project_uki_metadata",
    "project_verity_metadata",
    "write_build_metadata",
)
load(
    ":mkosi_action.bzl",
    "MKOSI_BUILD_ATTRS",
    "MKOSI_BUILD_EXEC_CONSTRAINTS",
    "MKOSI_BUILD_TOOLCHAINS",
    "add_build_arguments",
    "add_output_arguments",
    "add_release_arguments",
    "add_staging_arguments",
    "mkosi_arguments",
    "mkosi_tool_inputs",
    "run_mkosi",
)
load(":python_action.bzl", "MKOSI_TOOLCHAIN_TYPE", "run_python")
load(":staging.bzl", "executable_paths", "normalise_destination", "normalise_image_destination", "stage_inputs")

MkosiImageInfo = provider(
    doc = """Outputs of mkosi_image.

Select artifacts through these fields rather than DefaultInfo filenames. Every artifact field is a File or None,
and DefaultInfo contains every artifact that is not None. raw_image and build_metadata are always set, release
images add partition_metadata, and UEFI release images add their UKI, split dm-verity artifacts and metadata.
""",
    fields = {
        "format_version": "Contract version, currently mkosi-image-v3.",
        "raw_image": "The raw disk image.",
        "manifest": "The mkosi manifest; currently always None.",
        "partition_metadata": "Validated, normalized GPT partition metadata of a release image, or None.",
        "uki": "The unsigned Unified Kernel Image, or None.",
        "root_image": "Split root filesystem partition, or None.",
        "root_hash": "ASCII dm-verity root hash, or None.",
        "root_hash_image": "Split dm-verity hash partition, or None.",
        "uki_metadata": "Normalized UKI section metadata, or None.",
        "verity_metadata": "Normalized dm-verity linkage metadata, or None.",
        "build_metadata": "Normalized JSON metadata describing the build settings and output roles.",
        "firmware": "Firmware tier: uefi or bios.",
        "image_id": "os-release IMAGE_ID set by the rule, or None.",
        "image_version": "os-release IMAGE_VERSION set by the rule during analysis, or None.",
        "image_version_file": """File holding the os-release IMAGE_VERSION set through image_version_file, or None.

The content is letters, digits and '.', optionally followed by one newline. At most one of image_version and
image_version_file is set.""",
        "image": "Deprecated alias for raw_image.",
    },
)

MkosiConfigTreeInfo = provider(
    doc = "An mkosi configuration directory.",
    fields = {
        "tree": "The configuration directory artifact.",
        "executable_paths": "Relative paths that must keep their executable mode.",
        "is_generated": "Whether the tree is a generated TreeArtifact.",
    },
)

MkosiBaseInfo = provider(
    doc = """Version-independent root and initrd of a release image, built by mkosi_base.

mkosi_image(base = ...) finalizes it for one image version.
""",
    fields = {
        "format_version": "Contract version, currently mkosi-base-v1.",
        "root_tree": "Reproducible tar archive of the installed root, used as mkosi BaseTrees=.",
        "initrd": "mkosi's default initrd for root_tree, used as mkosi Initrds=.",
        "debian_snapshot": "DebianSnapshotInfo of the packages in root_tree and initrd.",
        "release_seed": "Seed= UUID shared by the base and its finalization.",
        "release_source_date_epoch": "SourceDateEpoch= shared by the base and its finalization.",
    },
)

MkosiSourceTreeInfo = provider(
    doc = "A directory mounted for mkosi BuildSources=.",
    fields = {
        "tree": "The source directory artifact.",
        "executable_paths": "Relative paths that must keep their executable mode.",
        "is_generated": "Whether the tree is a generated TreeArtifact.",
    },
)

MkosiRootfsPayloadInfo = provider(
    doc = "A file or directory installed at an absolute destination in the image root.",
    fields = {
        "artifact": "The file or directory artifact.",
        "destination": "Normalized absolute destination in the image root.",
        "executable_paths": "Relative paths in a directory, or [''] for a file, that must be executable.",
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
            doc = "A configuration directory that contains mkosi.conf.",
        ),
        "executable_paths": attr.string_list(
            doc = "Relative configuration-tree paths that must be executable.",
        ),
    },
    doc = "Marks a directory as an mkosi configuration tree.",
)

mkosi_source_tree = rule(
    implementation = lambda ctx: _tree_target_impl(ctx, MkosiSourceTreeInfo),
    attrs = {
        "src": attr.label(
            mandatory = True,
            allow_files = True,
            doc = "A directory mounted for mkosi BuildSources=.",
        ),
        "executable_paths": attr.string_list(
            doc = "Relative source-tree paths that must be executable.",
        ),
    },
    doc = "Marks a directory as an mkosi BuildSources= tree.",
)

def _single_input(target, attribute):
    files = target.files.to_list()
    if len(files) != 1:
        fail("{} must resolve to exactly one single file or directory, got {}".format(attribute, len(files)))
    return files[0]

def _rootfs_payload_impl(ctx):
    artifact = _single_input(ctx.attr.src, "src")
    destination = normalise_image_destination(ctx.attr.destination)
    is_tree = artifact.is_directory
    executable_paths = ctx.attr.executable_paths
    if not is_tree and executable_paths not in ([], [""]):
        fail("file rootfs payload executable_paths must be empty or ['']")
    for path in executable_paths:
        if path:
            normalise_destination(path, "executable_paths")
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
            doc = "A single source or generated file or directory.",
        ),
        "destination": attr.string(
            mandatory = True,
            doc = "Normalized absolute path at which to install the file or the directory contents.",
        ),
        "executable_paths": attr.string_list(
            doc = "Relative paths in a directory to make executable; use [''] for an executable file.",
        ),
    },
    doc = "Declares a root-owned file or directory to install into an image.",
)

def _reproducibility_arguments(ctx, image, split_artifacts, output):
    arguments = ctx.actions.args()
    arguments.add(ctx.file._projector.path)
    arguments.add("--raw-image")
    arguments.add(image.raw_image.path)
    arguments.add("--build-metadata")
    arguments.add(image.build_metadata.path)
    arguments.add("--partition-metadata")
    arguments.add(image.partition_metadata.path)
    for role, artifact in split_artifacts:
        arguments.add("--artifact")
        arguments.add(role)
        arguments.add(artifact.path)
    arguments.add("--output")
    arguments.add(output.path)
    return arguments

def _mkosi_reproducibility_manifest_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    if image.raw_image == None or image.build_metadata == None or image.partition_metadata == None:
        fail("image must provide raw_image, build_metadata, and partition_metadata")
    split_artifacts = [
        (role, getattr(image, role))
        for role in ["root_image", "root_hash", "root_hash_image", "uki", "uki_metadata", "verity_metadata"]
        if getattr(image, role) != None
    ]
    output = ctx.actions.declare_file(ctx.label.name + ".reproducibility.json")
    arguments = _reproducibility_arguments(ctx, image, split_artifacts, output)
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [
            image.raw_image,
            image.build_metadata,
            image.partition_metadata,
            ctx.file._partition_projector,
            ctx.file._projector,
            ctx.file._gpt_partitions,
            ctx.file._sibling_loader,
        ] + [artifact for _, artifact in split_artifacts],
        outputs = [output],
        mnemonic = "MkosiReproducibilityManifest",
        progress_message = "Projecting reproducibility manifest for %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

mkosi_reproducibility_manifest = rule(
    implementation = _mkosi_reproducibility_manifest_impl,
    attrs = {
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
            doc = "Release image whose immutable outputs are hashed.",
        ),
        "_gpt_partitions": attr.label(
            cfg = "exec",
            default = "//mkosi/private:gpt_partitions.py",
            allow_single_file = True,
        ),
        "_sibling_loader": attr.label(
            cfg = "exec",
            default = "//mkosi/private:sibling_loader.py",
            allow_single_file = True,
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
    doc = "Writes a normalized JSON manifest of the content hashes of a release image's immutable outputs.",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)

def _release_from_attrs(ctx):
    return struct(
        snapshot = ctx.attr.debian_snapshot[DebianSnapshotInfo],
        seed = ctx.attr.release_seed,
        source_date_epoch = ctx.attr.release_source_date_epoch,
    )

def _output_modes(ctx):
    release_mode = ctx.attr.mode == "release"
    firmware = ctx.attr.firmware
    uki = ctx.attr.unified_kernel_image == "unsigned"
    verity = ctx.attr.verity == "hash"
    if ctx.attr.mode not in ("tracer", "release"):
        fail("mode must be either 'tracer' or 'release'")
    if firmware not in ("uefi", "bios"):
        fail("firmware must be either 'uefi' or 'bios'")
    if firmware == "bios" and not release_mode:
        fail("bios firmware requires release mode")
    if firmware == "bios" and (uki or verity):
        fail("UKI and dm-verity outputs require uefi firmware")
    if ctx.attr.unified_kernel_image not in ("none", "unsigned"):
        fail("unified_kernel_image must be 'none' or 'unsigned'; signing is tracked by #23")
    if ctx.attr.verity not in ("none", "hash"):
        fail("verity must be 'none' or 'hash'; signing is tracked by #23")
    if (uki or verity) and not release_mode:
        fail("UKI and dm-verity outputs are only supported in release mode")
    if verity and not uki:
        fail("verity='hash' requires unified_kernel_image='unsigned' so the root hash is linked into the UKI")
    return struct(mode = ctx.attr.mode, release_mode = release_mode, firmware = firmware, uki = uki, verity = verity)

def _validate_base(ctx, modes):
    if not modes.release_mode:
        fail("base requires release mode")
    if ctx.attr.debian_snapshot or ctx.attr.release_seed or ctx.attr.release_source_date_epoch >= 0:
        fail("debian_snapshot, release_seed, and release_source_date_epoch come from base; do not set them")
    if modes.firmware != "uefi":
        fail("base requires uefi firmware")
    if ctx.attr.source_trees:
        fail("source_trees cannot be combined with base")

def _validate_release_attrs(ctx, release_mode, base):
    if release_mode and not base and not ctx.attr.debian_snapshot:
        fail("release mode requires debian_snapshot")
    if not release_mode and ctx.attr.debian_snapshot:
        fail("debian_snapshot is only supported in release mode")
    if release_mode and not base and not ctx.attr.release_seed:
        fail("release mode requires release_seed")
    if release_mode and not base and ctx.attr.release_source_date_epoch < 0:
        fail("release mode requires a non-negative release_source_date_epoch")
    if not release_mode and (ctx.attr.release_seed or ctx.attr.release_source_date_epoch >= 0):
        fail("release_seed and release_source_date_epoch are only supported in release mode")

def _release_source(ctx, modes):
    """Returns the MkosiBaseInfo to finalize, or None, and the release struct, or None in tracer mode."""
    base = ctx.attr.base[MkosiBaseInfo] if ctx.attr.base else None
    if base:
        _validate_base(ctx, modes)
    _validate_release_attrs(ctx, modes.release_mode, base)
    if base:
        return base, struct(
            snapshot = base.debian_snapshot,
            seed = base.release_seed,
            source_date_epoch = base.release_source_date_epoch,
        )
    if modes.release_mode:
        return None, _release_from_attrs(ctx)
    return None, None

def _image_identity(ctx, verity):
    image_id = ctx.expand_make_variables("image_id", ctx.attr.image_id, {}) or None
    image_version = ctx.expand_make_variables("image_version", ctx.attr.image_version, {}) or None
    image_version_file = ctx.file.image_version_file
    if image_version and image_version_file:
        fail("set at most one of image_version and image_version_file")
    if image_version and not image_id:
        fail("image_version requires image_id")
    if image_version_file and not image_id:
        fail("image_version_file requires image_id")
    if image_id:
        validate_image_id(image_id)
    if image_version:
        validate_image_version(image_version)
        if verity:
            validate_slot_labels(image_id, image_version)
    return struct(image_id = image_id, image_version = image_version, image_version_file = image_version_file)

def _config(ctx, release_mode):
    """Returns the configuration artifact and its MkosiConfigTreeInfo, or None for a single file."""
    if ctx.attr.config and ctx.attr.config_tree:
        fail("set exactly one of config and config_tree")
    if not ctx.attr.config and not ctx.attr.config_tree:
        fail("one of config or config_tree is required")
    if not ctx.attr.config_tree:
        if release_mode:
            fail("release mode requires config_tree so every configuration path is declared")
        return _single_input(ctx.attr.config, "config"), None
    config_info = ctx.attr.config_tree[MkosiConfigTreeInfo]
    return config_info.tree, config_info

def _image_settings(ctx):
    """Validates the mkosi_image attributes and returns the resolved build settings."""
    modes = _output_modes(ctx)
    base, release = _release_source(ctx, modes)
    identity = _image_identity(ctx, modes.verity)
    config, config_info = _config(ctx, modes.release_mode)
    if modes.firmware == "bios" and release.snapshot.architecture != "amd64":
        fail("bios firmware requires an amd64 Debian snapshot")
    return struct(
        mode = modes.mode,
        release_mode = modes.release_mode,
        firmware = modes.firmware,
        uki = modes.uki,
        verity = modes.verity,
        base = base,
        release = release,
        image_id = identity.image_id,
        image_version = identity.image_version,
        image_version_file = identity.image_version_file,
        config = config,
        config_info = config_info,
        source_trees = {destination: target[MkosiSourceTreeInfo] for destination, target in ctx.attr.source_trees.items()},
        rootfs_payloads = [target[MkosiRootfsPayloadInfo] for target in ctx.attr.rootfs_payloads],
    )

def _declare_file(ctx, suffix, enabled = True):
    return ctx.actions.declare_file(ctx.label.name + suffix) if enabled else None

def _declare_outputs(ctx, settings):
    return struct(
        raw_image = _declare_file(ctx, ".raw"),
        manifest = None,
        partition_metadata = _declare_file(ctx, ".partitions.json", settings.release_mode),
        uki = _declare_file(ctx, ".efi", settings.uki),
        root_image = _declare_file(ctx, ".root.raw", settings.verity),
        root_hash = _declare_file(ctx, ".roothash", settings.verity),
        root_hash_image = _declare_file(ctx, ".root-verity.raw", settings.verity),
        uki_metadata = _declare_file(ctx, ".uki.json", settings.uki),
        verity_metadata = _declare_file(ctx, ".verity.json", settings.verity),
        build_metadata = _declare_file(ctx, ".mkosi-image-info.json"),
    )

def _bios_partition_definition(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".bios-repart")
    run_python(
        ctx,
        arguments = [ctx.file._write_bios_repart.path, output.path],
        inputs = [ctx.file._write_bios_repart, ctx.file._gpt_partitions, ctx.file._sibling_loader],
        outputs = [output],
        mnemonic = "MkosiBiosRepart",
    )
    return output

def _image_runner_arguments(ctx, settings, staging):
    arguments = mkosi_arguments(ctx)
    base = settings.base
    if settings.release:
        add_release_arguments(arguments, settings.release, settings.firmware, snapshot_repository = not base)
    if base:
        arguments.add("--release-base-tree")
        arguments.add(base.root_tree.path)
        arguments.add("--release-initrd")
        arguments.add(base.initrd.path)
    add_staging_arguments(
        arguments,
        executable_paths(settings.config_info, settings.source_trees, settings.rootfs_payloads),
        staging,
    )
    if settings.image_version_file:
        arguments.add("--image-version-file")
        arguments.add(settings.image_version_file.path)
        if settings.verity:
            arguments.add("--slot-label-image-id")
            arguments.add(settings.image_id)
    arguments.add("--")
    return arguments

def _add_config_arguments(arguments, settings, staging):
    if not staging:
        arguments.add("-I")
        arguments.add(settings.config.path)
        return
    arguments.add("-C")
    arguments.add(staging.tree.path)
    if not settings.config_info and settings.config.basename != "mkosi.conf":
        arguments.add("-I")
        arguments.add(staging.tree.path + "/" + settings.config.basename)

_BIOS_PACKAGES = ["grub-pc-bin", "grub-common", "grub2-common", "initramfs-tools", "linux-image-amd64", "systemd-sysv"]

def _add_bios_arguments(arguments, partition_definition):
    arguments.add("--architecture=x86-64")
    arguments.add("--bootable=yes")
    arguments.add("--bootloader=none")
    arguments.add("--bios-bootloader=grub")
    for package in _BIOS_PACKAGES:
        arguments.add("--package=" + package)
    arguments.add("--repart-directory")
    arguments.add(partition_definition.path)

def _add_image_options(arguments, settings):
    if settings.uki:
        arguments.add("--unified-kernel-images=unsigned")
    if settings.base:
        arguments.add("--base-tree")
        arguments.add(settings.base.root_tree.path)
        arguments.add("--initrd")
        arguments.add(settings.base.initrd.path)

        # Finalization installs no packages, so it must not try to refresh package metadata over the blocked network.
        arguments.add("--cache-only=always")
    if settings.image_id:
        arguments.add("--image-id=" + settings.image_id)
    if settings.image_version:
        arguments.add("--image-version=" + settings.image_version)

def _image_arguments(ctx, settings, staging, image, bios_partition_definition):
    workspace = image.dirname + "/." + ctx.label.name + "-mkosi"
    arguments = _image_runner_arguments(ctx, settings, staging)
    _add_config_arguments(arguments, settings, staging)
    split_artifacts = "uki,partitions,roothash" if settings.verity else "uki" if settings.uki else ""
    add_output_arguments(arguments, ctx, workspace, "disk", split_artifacts)
    _add_image_options(arguments, settings)
    if bios_partition_definition:
        _add_bios_arguments(arguments, bios_partition_definition)
    add_build_arguments(
        arguments,
        output_directory = image.dirname,
        output_name = image.basename[:-len(".raw")],
        workspace = workspace,
        build_sources = bool(settings.source_trees),
        debug = settings.uki,
    )
    return arguments

def _image_build_inputs(ctx, settings, staging, bios_partition_definition):
    base = settings.base
    image_version_file = settings.image_version_file
    return (
        [settings.config] + mkosi_tool_inputs(ctx) +
        ([image_version_file, ctx.file._image_version] if image_version_file else []) +
        ([bios_partition_definition] if bios_partition_definition else []) +
        ([base.root_tree, base.initrd] if base else []) +
        ([settings.release.snapshot.repository] if settings.release and not base else []) +
        ([staging.tree, staging.manifest] if staging else [])
    )

def _build_image(ctx, settings, staging, outputs):
    bios_partition_definition = _bios_partition_definition(ctx) if settings.firmware == "bios" else None
    built = [outputs.raw_image, outputs.uki, outputs.root_image, outputs.root_hash, outputs.root_hash_image]
    run_mkosi(
        ctx,
        arguments = _image_arguments(ctx, settings, staging, outputs.raw_image, bios_partition_definition),
        inputs = _image_build_inputs(ctx, settings, staging, bios_partition_definition),
        outputs = [output for output in built if output != None],
        release = settings.release,
        mnemonic = "MkosiImage",
        progress_message = "Building mkosi image %{label}",
    )

_ARTIFACT_FIELDS = [
    "raw_image",
    "manifest",
    "partition_metadata",
    "uki",
    "root_image",
    "root_hash",
    "root_hash_image",
    "uki_metadata",
    "verity_metadata",
    "build_metadata",
]

def _image_providers(settings, outputs):
    artifacts = {field: getattr(outputs, field) for field in _ARTIFACT_FIELDS}
    return [
        DefaultInfo(files = depset([artifact for artifact in artifacts.values() if artifact != None])),
        MkosiImageInfo(
            format_version = "mkosi-image-v3",
            firmware = settings.firmware,
            image_id = settings.image_id,
            image_version = settings.image_version,
            image_version_file = settings.image_version_file,
            image = outputs.raw_image,
            **artifacts
        ),
    ]

def _mkosi_image_impl(ctx):
    settings = _image_settings(ctx)
    staging = None
    if settings.config_info or settings.source_trees or settings.rootfs_payloads:
        staging = stage_inputs(ctx, settings.config, settings.config_info, settings.source_trees, settings.rootfs_payloads)
    outputs = _declare_outputs(ctx, settings)
    _build_image(ctx, settings, staging, outputs)
    if settings.release_mode:
        project_partition_metadata(ctx, settings, outputs)
    if settings.uki:
        project_uki_metadata(ctx, outputs)
    if settings.verity:
        project_verity_metadata(ctx, outputs)
    write_build_metadata(ctx, settings, outputs.build_metadata)
    return _image_providers(settings, outputs)

mkosi_image = rule(
    implementation = _mkosi_image_impl,
    attrs = {
        "mode": attr.string(
            default = "tracer",
            doc = """"tracer" (default) installs packages from the network and is never cached; "release" installs packages
only from debian_snapshot or base with the network blocked and may be cached. Both run locally only.""",
        ),
        "firmware": attr.string(
            default = "uefi",
            doc = """"uefi" (default) or "bios", a release-only x86-64 tier that boots with GRUB i386-pc from a GPT BIOS
boot partition.""",
        ),
        "base": attr.label(
            providers = [MkosiBaseInfo],
            doc = """mkosi_base to finalize for this image version instead of installing packages.

Requires release mode and uefi firmware. The base provides the Debian snapshot, Seed= and SourceDateEpoch=, so
debian_snapshot, release_seed and release_source_date_epoch must be unset. The configuration must not install or
remove packages and holds only version-dependent settings, such as mkosi.repart/, the boot loader, the UKI and the
kernel command line.
""",
        ),
        "debian_snapshot": attr.label(
            providers = [DebianSnapshotInfo],
            doc = "Authenticated Debian snapshot; required in release mode unless base is set.",
        ),
        "release_seed": attr.string(
            doc = "Fixed UUID matching the configuration's resolved Seed=; required in release mode unless base is set.",
        ),
        "release_source_date_epoch": attr.int(
            default = -1,
            doc = """Non-negative timestamp matching the configuration's resolved SourceDateEpoch=; required in release
mode unless base is set.""",
        ),
        "unified_kernel_image": attr.string(
            default = "none",
            doc = """"none" (default) or "unsigned" to build an unsigned UKI. Requires release mode and uefi firmware;
sign it with secure_boot_signing_request.""",
        ),
        "verity": attr.string(
            default = "none",
            doc = """"none" (default) or "hash" to split the root into dm-verity data and hash partitions. Requires
unified_kernel_image = "unsigned".""",
        ),
        "config": attr.label(
            allow_files = True,
            doc = "A single mkosi configuration file. Set exactly one of config and config_tree; release mode requires " +
                  "config_tree.",
        ),
        "config_tree": attr.label(
            providers = [MkosiConfigTreeInfo],
            doc = "A complete mkosi configuration tree from mkosi_config_tree.",
        ),
        "source_trees": attr.string_keyed_label_dict(
            allow_files = True,
            providers = [MkosiSourceTreeInfo],
            doc = """mkosi_source_tree targets keyed by the normalized relative BuildSources= path, such as "src", at
which their contents are staged.""",
        ),
        "rootfs_payloads": attr.label_list(
            providers = [MkosiRootfsPayloadInfo],
            doc = "mkosi_rootfs_payload targets installed into the image root through mkosi.extra.",
        ),
        "image_id": attr.string(
            doc = """os-release IMAGE_ID passed to mkosi as ImageId=, overriding the configuration.

Lowercase letters, digits, '.', '-' and '_' only. Make variables are expanded.
""",
        ),
        "image_version": attr.string(
            doc = """os-release IMAGE_VERSION passed to mkosi as ImageVersion=, overriding the configuration.

Requires image_id and excludes image_version_file. Letters, digits and '.' only, so that systemd-sysupdate can
split '<image_id>_<image_version>' and '+'/'-' stay free for systemd-boot boot counting. Make variables are
expanded, e.g. image_version = "$(OS_VERSION)" with a TemplateVariableInfo target in `toolchains`.

With verity = "hash", the populated root and verity partitions must be labelled '<image_id>_<image_version>' and
'<image_id>_<image_version>_verity' (repart Label=%M_%A and Label=%M_%A_verity), and inactive A/B slots '_empty',
as sysupdate_transfers and sysupdate_payload expect. The verity label must fit the 36-character GPT partition
name limit.
""",
        ),
        "image_version_file": attr.label(
            allow_single_file = True,
            doc = """File containing the os-release IMAGE_VERSION, for versions known only at execution time.

Use it for build-derived versions, such as a stamped genrule. Requires image_id and excludes image_version. The
content must satisfy the image_version constraints, optionally followed by one newline; the actions that read the
file enforce them. MkosiImageInfo then sets image_version_file instead of image_version.
""",
        ),
        "_write_bios_repart": attr.label(
            cfg = "exec",
            default = "//mkosi/private:write_bios_repart.py",
            allow_single_file = True,
        ),
    } | MKOSI_BUILD_ATTRS | IMAGE_METADATA_ATTRS,
    doc = """Builds a raw disk image with the pinned mkosi and Debian toolchains.

Tracer mode installs packages from the network and is never cached. Release mode installs packages only from an
authenticated debian_snapshot with the network blocked, so its outputs may be cached; with base, it finalizes a
cached mkosi_base for one version instead. Builds run locally and need the Linux namespace and mount capabilities
of the host-kernel contract.

Select outputs through MkosiImageInfo; DefaultInfo contains every produced artifact.
""",
    provides = [MkosiImageInfo],
    toolchains = MKOSI_BUILD_TOOLCHAINS,
    exec_compatible_with = MKOSI_BUILD_EXEC_CONSTRAINTS,
)

def _base_arguments(ctx, release, config_info, rootfs_payloads, staging, root_tree, initrd):
    output_directory = root_tree.dirname
    workspace = output_directory + ".workspace"
    arguments = mkosi_arguments(ctx)
    add_release_arguments(arguments, release, "uefi", snapshot_repository = True)
    add_staging_arguments(arguments, executable_paths(config_info, {}, rootfs_payloads), staging)
    arguments.add("--release-base-initrd-output")
    arguments.add(initrd.path)
    arguments.add("--")
    arguments.add("-C")
    arguments.add(staging.tree.path)
    add_output_arguments(arguments, ctx, workspace, "tar", "")

    # Without a kernel installation the base contains no UKI or boot loader, which depend on the version. The
    # default initrd is requested explicitly because mkosi builds it only for bootable images, and INITRD=No keeps
    # the kernel package from generating a distribution initrd, as mkosi does for bootable images.
    arguments.add("--bootable=no")
    arguments.add("--initrd=default")
    arguments.add("--environment=INITRD=No")
    add_build_arguments(arguments, output_directory, "root", workspace, build_sources = False, debug = False)
    return arguments

def _mkosi_base_impl(ctx):
    if not ctx.attr.release_seed:
        fail("mkosi_base requires release_seed")
    if ctx.attr.release_source_date_epoch < 0:
        fail("mkosi_base requires a non-negative release_source_date_epoch")
    release = _release_from_attrs(ctx)
    config_info = ctx.attr.config_tree[MkosiConfigTreeInfo]
    rootfs_payloads = [target[MkosiRootfsPayloadInfo] for target in ctx.attr.rootfs_payloads]
    staging = stage_inputs(ctx, config_info.tree, config_info, {}, rootfs_payloads)
    root_tree = ctx.actions.declare_file(ctx.label.name + ".mkosi-base/root.tar")
    initrd = ctx.actions.declare_file(ctx.label.name + ".initrd")
    run_mkosi(
        ctx,
        arguments = _base_arguments(ctx, release, config_info, rootfs_payloads, staging, root_tree, initrd),
        inputs = [config_info.tree, release.snapshot.repository, staging.tree, staging.manifest] + mkosi_tool_inputs(ctx),
        outputs = [root_tree, initrd],
        release = release,
        mnemonic = "MkosiBase",
        progress_message = "Building mkosi base %{label}",
    )
    return [
        DefaultInfo(files = depset([root_tree, initrd])),
        MkosiBaseInfo(
            format_version = "mkosi-base-v1",
            root_tree = root_tree,
            initrd = initrd,
            debian_snapshot = release.snapshot,
            release_seed = release.seed,
            release_source_date_epoch = release.source_date_epoch,
        ),
    ]

mkosi_base = rule(
    implementation = _mkosi_base_impl,
    attrs = {
        "config_tree": attr.label(
            mandatory = True,
            providers = [MkosiConfigTreeInfo],
            doc = """Configuration of the version-independent part of a release, such as Packages=, RemoveFiles= and
mkosi.extra content. It is built with Format=tar and Bootable=no and must not set ImageVersion=.""",
        ),
        "debian_snapshot": attr.label(
            mandatory = True,
            providers = [DebianSnapshotInfo],
            doc = "Authenticated Debian snapshot; the only package source of the network-blocked build.",
        ),
        "release_seed": attr.string(
            doc = "Required fixed UUID matching the configuration's resolved Seed=.",
        ),
        "release_source_date_epoch": attr.int(
            default = -1,
            doc = "Required non-negative timestamp matching the configuration's resolved SourceDateEpoch=.",
        ),
        "rootfs_payloads": attr.label_list(
            providers = [MkosiRootfsPayloadInfo],
            doc = "Version-independent mkosi_rootfs_payload targets installed into the image root.",
        ),
    } | MKOSI_BUILD_ATTRS,
    doc = """Builds the version-independent root and default initrd of a release image.

Packages are installed from the authenticated debian_snapshot with the network blocked. The base has no partitions,
boot loader or UKI, so it does not depend on an image version: mkosi_image(base = ...) finalizes it for one version,
and a new version reuses the cached base.
""",
    provides = [MkosiBaseInfo],
    toolchains = MKOSI_BUILD_TOOLCHAINS,
    exec_compatible_with = MKOSI_BUILD_EXEC_CONSTRAINTS,
)
