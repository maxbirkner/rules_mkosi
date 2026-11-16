"""Local APT repository of the extra Debian packages that a build installs next to its Debian snapshot."""

load(":python_action.bzl", "run_python")

EXTRA_PACKAGES_DOC = """Debian binary packages (.deb files) to install in addition to the packages of the Debian snapshot,
such as a patched kernel or a vendor's firmware.

The build serves them to APT as a local repository next to the snapshot mirror, so the configuration selects them with
Packages= like snapshot packages, and dpkg installs them with their maintainer scripts. An extra package takes
precedence over a snapshot package of the same name whatever their versions, so it can replace one, such as
linux-image-amd64. Their dependencies must be in the snapshot or in extra_packages; APT resolves them offline and fails
with PACKAGE_RESOLUTION_FAILURE otherwise. mkosi's default initrd is built from the same repositories.

Each file must be a Debian binary package for the snapshot's architecture or for all, and no two may have the same
package name; the file name does not matter, so http_file's default `downloaded` works. The files are build inputs, so
they are part of the cache key and of a version derived with image_version_from_inputs; pin downloaded files by hash,
for example with http_file(sha256 = ...). The provider's extra_packages_metadata lists them.
"""

EXTRA_PACKAGES_ATTRS = {
    "_extra_packages_modules": attr.label_list(
        cfg = "exec",
        default = [
            "//mkosi/private:debian_control.py",
            "//mkosi/private:diagnostics.py",
            "//mkosi/private:file_hashing.py",
            "//mkosi/private:sibling_loader.py",
        ],
        allow_files = True,
    ),
    "_extra_packages_tool": attr.label(
        cfg = "exec",
        default = "//mkosi/private:extra_packages.py",
        allow_single_file = True,
    ),
}

def index_extra_packages(ctx, snapshot):
    """Registers the action that validates ctx.files.extra_packages and writes the index of their flat APT repository.

    The index holds no copy of the .deb files: the build places them next to it in its mirror of the snapshot, so a
    large package is copied once per build rather than twice.

    Args:
      ctx: Rule context with an extra_packages label list and EXTRA_PACKAGES_ATTRS.
      snapshot: DebianSnapshotInfo whose architecture the packages must have, unless they are for all.

    Returns:
      Struct with the index TreeArtifact, the .deb Files as packages, the metadata JSON File, and the inputs that a build
      which serves the repository reads, or None without extra packages.
    """
    packages = ctx.files.extra_packages
    if not packages:
        return None
    for package in packages:
        if package.is_directory:
            fail("extra_packages must be .deb files, but {} is a directory".format(package.short_path))
    index = ctx.actions.declare_directory(ctx.label.name + ".extra-packages")
    metadata = ctx.actions.declare_file(ctx.label.name + ".extra-packages.json")
    arguments = ctx.actions.args()
    arguments.add(ctx.file._extra_packages_tool.path)
    arguments.add("--architecture", snapshot.architecture)
    arguments.add("--index", index.path)
    arguments.add("--manifest", metadata.path)
    arguments.add_all(packages)
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [ctx.file._extra_packages_tool] + ctx.files._extra_packages_modules + packages,
        outputs = [index, metadata],
        mnemonic = "MkosiExtraPackages",
        progress_message = "Indexing extra Debian packages for %{label}",
    )
    return struct(index = index, packages = packages, metadata = metadata, inputs = [index] + packages)

def add_extra_packages_arguments(arguments, extra_packages):
    """Adds the runner options that serve the extra packages and their index next to the Debian snapshot mirror.

    Args:
      arguments: Args of the mkosi runner.
      extra_packages: Struct returned by index_extra_packages, or None.
    """
    if extra_packages:
        arguments.add("--extra-packages-index")
        arguments.add(extra_packages.index.path)
        arguments.add_all(extra_packages.packages, before_each = "--extra-package")
