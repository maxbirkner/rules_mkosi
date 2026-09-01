"""Implementation of the public mkosi_image rule."""

MkosiImageInfo = provider(
    doc = """Stable output contract for mkosi_image.

Consumers select artifacts through these fields, never by inspecting
DefaultInfo filenames. Every artifact field is either a File or None. The
raw_image and build_metadata fields are present for every currently supported
mkosi_image target; manifest, partition_metadata, and uki are reserved for
future output modes. DefaultInfo contains every non-None artifact field once.
The image field is a compatibility alias for raw_image.
""",
    fields = {
        "format_version": "Stable MkosiImageInfo contract version, currently mkosi-image-v1.",
        "raw_image": "The raw disk image File, or None when an output mode does not produce one.",
        "manifest": "The mkosi manifest File, or None when manifest generation is disabled.",
        "partition_metadata": "Normalized partition metadata File, or None until that projection is generated.",
        "uki": "The Unified Kernel Image File, or None when no UKI is generated.",
        "build_metadata": "Normalized JSON build-metadata File describing this contract's output modes.",
        "image": "Deprecated compatibility alias for raw_image; use raw_image in new consumers.",
    },
)

MkosiConfigTreeInfo = provider(
    doc = "Explicitly typed mkosi configuration tree.",
    fields = {
        "tree": "The declared configuration directory artifact.",
        "executable_paths": "Relative paths that must retain executable mode.",
    },
)

MkosiSourceTreeInfo = provider(
    doc = "Explicitly typed mkosi BuildSources tree.",
    fields = {
        "tree": "The declared source directory artifact.",
        "executable_paths": "Relative paths that must retain executable mode.",
    },
)

def _tree_target_impl(ctx, info):
    files = ctx.files.src
    if len(files) != 1:
        fail("{} must resolve to exactly one directory artifact".format(ctx.label))
    return [
        DefaultInfo(files = depset(files)),
        info(tree = files[0], executable_paths = ctx.attr.executable_paths),
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

def _stage_inputs(ctx, config, config_is_directory, source_trees):
    staging = ctx.actions.declare_directory(ctx.label.name + ".mkosi")
    manifest = ctx.actions.declare_file(ctx.label.name + ".mkosi.manifest")
    mappings = []

    if config_is_directory:
        mappings.append((config.path, ".", "tree"))
    else:
        mappings.append((config.path, config.basename, "file"))

    for destination in sorted(source_trees):
        mappings.append((source_trees[destination].tree.path, destination, "tree"))

    executable_paths = []
    if config_is_directory:
        executable_paths += ctx.attr.config_tree[MkosiConfigTreeInfo].executable_paths
    for destination in sorted(source_trees):
        executable_paths += [
            destination + "/" + path
            for path in source_trees[destination].executable_paths
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
            destination = _normalise_destination(destination, "source_trees")

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
            [source_trees[destination].tree for destination in sorted(source_trees)],
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

def _mkosi_image_impl(ctx):
    mkosi = ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi
    debian_tools = ctx.toolchains["//mkosi/toolchain:debian_tools_toolchain_type"].debian_tools
    if ctx.attr.config and ctx.attr.config_tree:
        fail("set exactly one of config and config_tree")
    if not ctx.attr.config and not ctx.attr.config_tree:
        fail("one of config or config_tree is required")

    config_is_directory = bool(ctx.attr.config_tree)
    config = (
        ctx.attr.config_tree[MkosiConfigTreeInfo].tree if config_is_directory else _single_input(ctx.attr.config, "config")
    )
    source_trees = {}
    for destination, target in ctx.attr.source_trees.items():
        source_trees[destination] = target[MkosiSourceTreeInfo]

    staging = None
    if config_is_directory or source_trees:
        staging = _stage_inputs(ctx, config, config_is_directory, source_trees)

    image = ctx.actions.declare_file(ctx.label.name + ".raw")
    build_metadata = ctx.actions.declare_file(
        ctx.label.name + ".mkosi-image-info.json",
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
    if config_is_directory:
        for path in ctx.attr.config_tree[MkosiConfigTreeInfo].executable_paths:
            arguments.add("--executable-path")
            arguments.add(path)
    for destination in sorted(source_trees):
        for path in source_trees[destination].executable_paths:
            arguments.add("--executable-path")
            arguments.add(destination + "/" + path)
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

    ctx.actions.run(
        executable = mkosi.python,
        arguments = [arguments],
        inputs = depset(
            [config, mkosi.script, ctx.file._run_script, ctx.file._diagnostics, ctx.executable._kernel_preflight, mkosi.pefile, debian_tools.tree, debian_tools.extractor] +
            ([staging.tree, staging.manifest] if staging else []),
            transitive = [mkosi.runfiles_files, mkosi.python_runtime_files],
        ),
        tools = [
            mkosi.python_files_to_run,
            ctx.attr._kernel_preflight[DefaultInfo].files_to_run,
        ],
        outputs = [image],
        env = {
            "PATH": "",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": mkosi_root + ":" + pefile_root,
        },
        execution_requirements = {
            "no-cache": "1",
            "no-remote-exec": "1",
            "requires-network": "1",
        },
        mnemonic = "MkosiImage",
        progress_message = "Building mkosi image %{label}",
    )

    # This projection deliberately records output roles and normalized mkosi
    # settings rather than deriving meaning from output filenames or binaries.
    ctx.actions.write(
        output = build_metadata,
        content = json.encode({
            "artifacts": {
                "build_metadata": True,
                "manifest": False,
                "partition_metadata": False,
                "raw_image": True,
                "uki": False,
            },
            "format_version": "mkosi-image-build-metadata-v1",
            "mkosi": {
                "compression": "none",
                "format": "disk",
                "split_artifacts": False,
                "version": mkosi.version,
            },
        }) + "\n",
    )

    return [
        _image_default_info(
            raw_image = image,
            manifest = None,
            partition_metadata = None,
            uki = None,
            build_metadata = build_metadata,
        ),
        MkosiImageInfo(
            format_version = "mkosi-image-v1",
            raw_image = image,
            manifest = None,
            partition_metadata = None,
            uki = None,
            build_metadata = build_metadata,
            image = image,
        ),
    ]

mkosi_image = rule(
    implementation = _mkosi_image_impl,
    attrs = {
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
        "_stage_script": attr.label(
            cfg = "exec",
            default = "//mkosi/private:stage_inputs.py",
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
        "_diagnostics": attr.label(
            cfg = "exec",
            default = "//mkosi/private:diagnostics.py",
            allow_single_file = True,
        ),
    },
    doc = """Builds a raw disk image using the pinned mkosi and Debian toolchains.

The action downloads target Debian packages over the network and requires the
Linux namespace and mount capabilities documented by the host-kernel contract.
It is intentionally non-cacheable and does not claim remote-execution or
offline hermeticity. MkosiImageInfo.raw_image and
MkosiImageInfo.build_metadata are present; manifest, partition_metadata, and
uki are None. DefaultInfo includes the raw image and build metadata, so
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
