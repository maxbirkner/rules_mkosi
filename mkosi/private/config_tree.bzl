"""mkosi_config_tree: declares an mkosi configuration directory or assembles one from files and trees."""

load(":mkosi_image.bzl", "MkosiConfigTreeInfo")
load(":python_action.bzl", "MKOSI_TOOLCHAIN_TYPE", "run_python")
load(":staging.bzl", "normalise_destination")

def _join(*parts):
    return "/".join([part for part in parts if part])

def _package_relative_path(file, label, attribute):
    """Returns the path of file relative to the package of label, which lists it."""
    path = file.path[len(file.root.path) + 1:] if file.root.path else file.path
    package = _join(label.workspace_root, label.package)
    if package and not path.startswith(package + "/"):
        fail("{} file {} is outside the package of {}".format(attribute, file.short_path, label))
    return path[len(package) + 1:] if package else path

def _role(artifact):
    return "tree" if artifact.is_source else "generated-tree"

def _single_directory(target):
    files = target.files.to_list()
    return files[0] if len(files) == 1 and files[0].is_directory else None

def _src_files(ctx):
    """Returns (artifact, destination) for every srcs file, with strip_prefix removed."""
    prefix = normalise_destination(ctx.attr.strip_prefix, "strip_prefix") if ctx.attr.strip_prefix else ""
    files = []
    for target in ctx.attr.srcs:
        for file in target.files.to_list():
            if file.is_directory:
                fail("srcs must contain files; map directory {} with src or trees".format(file.short_path))
            path = _package_relative_path(file, target.label, "srcs")
            if prefix and not path.startswith(prefix + "/"):
                fail("srcs file {} is not below strip_prefix '{}'".format(path, prefix))
            files.append((file, path[len(prefix) + 1:] if prefix else path))
    return files

def _tree_mappings(ctx):
    """Returns (files, directories, executable_paths) contributed by trees, keyed by normalized destination."""
    files, directories, executables = [], [], []
    for destination in sorted(ctx.attr.trees):
        target = ctx.attr.trees[destination]
        destination = normalise_destination(destination, "trees")
        directory = _single_directory(target)
        if MkosiConfigTreeInfo in target:
            directory = target[MkosiConfigTreeInfo].tree
            executables += [_join(destination, path) for path in target[MkosiConfigTreeInfo].executable_paths]
        if directory:
            directories.append((directory, destination))
            continue
        if not target.files.to_list():
            fail("trees entry '{}' provides no files".format(destination))
        for file in target.files.to_list():
            if file.is_directory:
                fail("trees entry '{}' mixes directory {} with other files".format(destination, file.short_path))
            files.append((file, _join(destination, _package_relative_path(file, target.label, "trees"))))
    return files, directories, executables

def _check_layout(files, directories):
    """Fails on duplicate file destinations and on files at or above another destination."""
    owners = {}
    parents = {}
    for _, destination in files + directories:
        parts = destination.split("/")
        for index in range(1, len(parts)):
            parents["/".join(parts[:index])] = destination
    for artifact, destination in files:
        if destination in owners:
            fail("duplicate configuration tree destination '{}' from {} and {}".format(
                destination,
                owners[destination].short_path,
                artifact.short_path,
            ))
        owners[destination] = artifact
        if destination in parents:
            fail("configuration tree file '{}' collides with '{}'".format(destination, parents[destination]))
    for _, destination in directories:
        if destination in owners:
            fail("configuration tree file '{}' collides with a trees directory".format(destination))
    return owners

def _check_executables(executables, owners, directories, has_root):
    """Fails on executable paths that are neither assembled files nor below a directory with unknown contents."""
    for path in executables:
        if has_root or path in owners or any([path.startswith(d + "/") for _, d in directories]):
            continue
        fail("executable_paths entry '{}' is not a file of the configuration tree".format(path))

def _assemble_arguments(ctx, output, mappings, executables):
    arguments = ctx.actions.args()
    arguments.add(ctx.file._stage_script.path)
    arguments.add("--merge")
    arguments.add("--output", output.path)
    for artifact, destination, role in mappings:
        arguments.add("--mapping")
        arguments.add_all([artifact.path, destination or ".", role])
    arguments.add_all(executables, before_each = "--executable")
    return arguments

def _assemble(ctx, src):
    """Registers the action that assembles the configuration tree and returns it with its executable paths."""
    files = _src_files(ctx)
    tree_files, directories, executables = _tree_mappings(ctx)
    files += tree_files
    owners = _check_layout(files, directories)
    executables = [normalise_destination(path, "executable_paths") for path in ctx.attr.executable_paths] + executables
    _check_executables(executables, owners, directories, src != None)
    if ctx.toolchains[MKOSI_TOOLCHAIN_TYPE] == None:
        fail("assembling a configuration tree from srcs or trees requires a registered mkosi toolchain")

    output = ctx.actions.declare_directory(ctx.label.name + ".config-tree")
    mappings = ([(src, "", _role(src))] if src else []) + [
        (artifact, destination, "file")
        for artifact, destination in files
    ] + [(directory, destination, _role(directory)) for directory, destination in directories]
    run_python(
        ctx,
        arguments = [_assemble_arguments(ctx, output, mappings, executables)],
        inputs = [ctx.file._stage_script] + [mapping[0] for mapping in mappings],
        outputs = [output],
        mnemonic = "MkosiConfigTree",
        progress_message = "Assembling mkosi configuration tree %{label}",
    )
    return output, executables

def _mkosi_config_tree_impl(ctx):
    src = None
    if ctx.attr.src:
        files = ctx.files.src
        if len(files) != 1:
            fail("{} must resolve to exactly one directory artifact".format(ctx.label))
        src = files[0]
    if not ctx.attr.srcs and not ctx.attr.trees:
        if not src:
            fail("set src, srcs, or trees")
        tree, executables = src, ctx.attr.executable_paths
    else:
        tree, executables = _assemble(ctx, src)
    return [
        DefaultInfo(files = depset([tree])),
        MkosiConfigTreeInfo(tree = tree, executable_paths = executables, is_generated = not tree.is_source),
    ]

mkosi_config_tree = rule(
    implementation = _mkosi_config_tree_impl,
    attrs = {
        "executable_paths": attr.string_list(
            doc = "Relative configuration-tree paths that must be executable.",
        ),
        "src": attr.label(
            allow_files = True,
            doc = "A configuration directory whose contents form the root of the tree.",
        ),
        "srcs": attr.label_list(
            allow_files = True,
            doc = """Files placed at their path relative to the package of the listed target, without strip_prefix,
such as glob(["mkosi/**"]).""",
        ),
        "strip_prefix": attr.string(
            doc = "Normalized package-relative directory removed from every srcs path; srcs must all be below it.",
        ),
        "trees": attr.string_keyed_label_dict(
            allow_files = True,
            doc = """Targets keyed by the normalized relative directory below which they are placed, such as
"mkosi.extra" or "mkosi.initrd.conf/mkosi.extra"; a target may appear under several keys.

An mkosi_config_tree contributes its contents and executable_paths, and a single generated directory its contents.
Any other target contributes its files at their path relative to its package. To place the contents of a source
directory, wrap it in an mkosi_config_tree with src.""",
        ),
        "_stage_script": attr.label(
            cfg = "exec",
            default = "//mkosi/private:stage_inputs.py",
            allow_single_file = True,
        ),
    },
    doc = """Declares an mkosi configuration tree, or assembles one from src, srcs, and trees.

With only src, the directory is used as is. Otherwise one action copies every input into a new directory with
deterministic modes and timestamps: directories merge, while traversal, absolute paths, duplicate files, and files
that collide with directories fail, at analysis time where the paths are known.
""",
    provides = [MkosiConfigTreeInfo],
    toolchains = [config_common.toolchain_type(MKOSI_TOOLCHAIN_TYPE, mandatory = False)],
)
