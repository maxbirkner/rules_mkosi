"""Staging of mkosi configuration, source trees and rootfs payloads into one directory."""

load(":python_action.bzl", "run_python")

def normalise_destination(destination, attribute):
    """Validates a relative path inside the staged mkosi directory.

    Args:
      destination: Relative path.
      attribute: Attribute name used in failure messages.

    Returns:
      The normalized path.
    """
    if not destination:
        fail("{} entries must have a non-empty relative destination".format(attribute))
    if destination.startswith("/") or "\\" in destination:
        fail("{} destination '{}' must be relative".format(attribute, destination))

    parts = destination.split("/")
    if any([part in ("", ".", "..") for part in parts]):
        fail("{} destination '{}' is not a normalized relative path".format(attribute, destination))
    return "/".join(parts)

def normalise_image_destination(destination):
    """Returns a validated, normalized absolute path below the image root."""
    if not destination.startswith("/") or destination == "/":
        fail("rootfs payload destination '{}' must be an absolute path below /".format(destination))
    return "/" + normalise_destination(destination[1:], "rootfs payload")

def _tree_role(is_generated):
    return "generated-tree" if is_generated else "tree"

def _payload_role(payload):
    return _tree_role(payload.is_generated) if payload.is_tree else "file"

def _payload_destination(payload):
    return "mkosi.extra" + payload.destination

def executable_paths(config_info, source_trees, rootfs_payloads):
    """Returns the staged paths that must keep their executable mode.

    Args:
      config_info: MkosiConfigTreeInfo of the configuration, or None for a single configuration file.
      source_trees: Dict from staged destination to MkosiSourceTreeInfo.
      rootfs_payloads: List of MkosiRootfsPayloadInfo.

    Returns:
      A list of relative paths in the staged directory.
    """
    paths = list(config_info.executable_paths) if config_info else []
    for destination in sorted(source_trees):
        paths += [destination + "/" + path for path in source_trees[destination].executable_paths]
    for payload in rootfs_payloads:
        prefix = _payload_destination(payload)
        paths += [prefix + (("/" + path) if path else "") for path in payload.executable_paths]
    return paths

def _mappings(config, config_info, source_trees, rootfs_payloads):
    """Returns (source path, staged destination, role) for every staged input."""
    if config_info:
        mappings = [(config.path, ".", _tree_role(config_info.is_generated))]
    else:
        mappings = [(config.path, config.basename, "file")]
    for destination in sorted(source_trees):
        tree = source_trees[destination]
        mappings.append((tree.tree.path, destination, _tree_role(tree.is_generated)))
    for payload in rootfs_payloads:
        mappings.append((payload.artifact.path, _payload_destination(payload), _payload_role(payload)))
    return mappings

def _staged_destination(destination):
    if destination == ".":
        return ""
    return normalise_destination(destination, "staged inputs") if destination else destination

def _check_mappings(mappings):
    """Fails unless every staged source and destination is unique and no destination is nested in another."""
    destinations = {}
    sources = {}
    for source, destination, _ in mappings:
        destination = _staged_destination(destination)
        if destination in destinations:
            fail("duplicate staged destination '{}' from {} and {}".format(
                destination or ".",
                destinations[destination],
                source,
            ))
        destinations[destination] = source
        if source in sources:
            fail("duplicate staged source '{}' at '{}' and '{}'".format(source, sources[source], destination or "."))
        sources[source] = destination

        # A source tree rooted below another source tree would have ambiguous
        # ownership even when the two labels happen to contain disjoint files.
        for other in destinations:
            if other == destination or not other:
                continue
            if destination.startswith(other + "/") or other.startswith(destination + "/"):
                fail("colliding staged destinations '{}' and '{}'".format(destination, other))

def _stage_arguments(ctx, staging, manifest, mappings, executables):
    arguments = ctx.actions.args()
    arguments.add(ctx.file._stage_script.path)
    arguments.add("--output")
    arguments.add(staging.path)
    arguments.add("--manifest")
    arguments.add(manifest.path)
    for source, destination, role in mappings:
        arguments.add("--mapping")
        arguments.add(source)
        arguments.add(destination)
        arguments.add(role)
    for path in executables:
        arguments.add("--executable")
        arguments.add(path)
    return arguments

def stage_inputs(ctx, config, config_info, source_trees, rootfs_payloads):
    """Registers the action that copies every mkosi input into one staged directory.

    Args:
      ctx: Rule context with a _stage_script attribute.
      config: Configuration file or directory artifact.
      config_info: MkosiConfigTreeInfo of a configuration directory, or None for a single file.
      source_trees: Dict from staged destination to MkosiSourceTreeInfo.
      rootfs_payloads: List of MkosiRootfsPayloadInfo.

    Returns:
      A struct with the staged directory `tree` and its `manifest`.
    """
    staging = ctx.actions.declare_directory(ctx.label.name + ".mkosi")
    manifest = ctx.actions.declare_file(ctx.label.name + ".mkosi.manifest")
    mappings = _mappings(config, config_info, source_trees, rootfs_payloads)
    executables = [
        normalise_destination(path, "executable_paths")
        for path in executable_paths(config_info, source_trees, rootfs_payloads)
    ]
    _check_mappings(mappings)

    arguments = _stage_arguments(ctx, staging, manifest, mappings, executables)
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [config, ctx.file._stage_script] +
                 [source_trees[destination].tree for destination in sorted(source_trees)] +
                 [payload.artifact for payload in rootfs_payloads],
        outputs = [staging, manifest],
        mnemonic = "MkosiStageInputs",
        progress_message = "Staging mkosi inputs for %{label}",
    )
    return struct(tree = staging, manifest = manifest)
