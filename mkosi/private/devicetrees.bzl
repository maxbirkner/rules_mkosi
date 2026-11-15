"""Device tree blobs that a release build stages for its UKI."""

load(":python_action.bzl", "run_python")

DEVICETREES_DOC = """Compiled device tree blobs (.dtb files) to embed in the image's UKI, for example from a
board vendor or another Bazel rule.

Requires release mode and unified_kernel_image. The build checks that each file is a flattened device tree with a
root compatible string, stages it as /usr/lib/firmware/<kver>/device-tree/rules-mkosi/<file name> for the kernel
version <kver> that the UKI is built for, and appends the pattern rules-mkosi/<file name> to the configuration's
Devicetrees=, so it is selected together with the device trees that Devicetrees= selects from packages. One selected
device tree becomes the UKI's .dtb section, which systemd-stub always installs; several become .dtbauto sections, of
which systemd-stub installs the one whose first compatible string matches the hardware. The staged files are only in
the UKI, not in the root file system. File names must be unique and consist of letters, digits, and `.`, `_`, `+`
and `-`. The files are build inputs, so a changed device tree changes the cache key and a version derived with
image_version_from_inputs; the UKI metadata records their compatible strings and digests.
"""

_FILE_NAME_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-"

def _validate_file_names(files):
    names = {}
    for file in files:
        if file.is_directory:
            fail("devicetrees must be .dtb files, but {} is a directory".format(file.short_path))
        name = file.basename
        if not name.endswith(".dtb") or [character for character in name.elems() if character not in _FILE_NAME_CHARACTERS]:
            fail("devicetrees file name {} must end with .dtb and consist of letters, digits, and . _ + -".format(
                file.short_path,
            ))
        if name in names:
            fail("devicetrees {} and {} have the same file name".format(names[name].short_path, file.short_path))
        names[name] = file

def stage_devicetrees(ctx, modes):
    """Validates ctx.files.devicetrees and registers the action that stages them, or returns None without any.

    Args:
      ctx: mkosi_image rule context with a devicetrees label list and the _devicetree script.
      modes: The image's output modes.

    Returns:
      The TreeArtifact holding the device trees by file name, or None.
    """
    files = ctx.files.devicetrees
    if not files:
        return None
    if not modes.release_mode:
        fail("devicetrees requires release mode")
    if not modes.uki:
        fail("devicetrees requires unified_kernel_image, which embeds them")
    _validate_file_names(files)
    directory = ctx.actions.declare_directory(ctx.label.name + ".devicetrees")
    arguments = ctx.actions.args()
    arguments.add(ctx.file._devicetree.path)
    arguments.add("--output-directory", directory.path)
    arguments.add_all(files)
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [ctx.file._devicetree] + files,
        outputs = [directory],
        mnemonic = "MkosiDevicetrees",
        progress_message = "Checking the device trees of %{label}",
    )
    return directory

def add_devicetrees_arguments(arguments, directory):
    """Adds the runner option that stages the device trees for the UKI.

    Args:
      arguments: Args of the mkosi runner.
      directory: TreeArtifact returned by stage_devicetrees, or None.
    """
    if directory:
        arguments.add("--devicetrees-directory")
        arguments.add(directory.path)
