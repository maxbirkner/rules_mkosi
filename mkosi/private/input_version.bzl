"""Derivation of an mkosi_image version from everything that its image build action reads."""

load(":mkosi_action.bzl", "mkosi_execution_requirements")
load(":python_action.bzl", "mkosi_toolchain_info", "run_python")

# Scripts of sysupdate_payload and secure_boot_signed_image, which turn an image into shipped bytes. A derived version
# covers them, and the Debian tools launcher that they run, so that a ruleset update that changes those bytes also
# changes the version. Tests check that the rules read no other ruleset script.
ARTIFACT_TOOL_SCRIPTS = [
    "efi_auth.py",
    "esp_files.py",
    "file_hashing.py",
    "gpt_partitions.py",
    "image_version.py",
    "launcher_tool.py",
    "secure_boot.py",
    "secure_boot_image.py",
    "sibling_loader.py",
    "sysupdate.py",
]

INPUT_VERSION_ATTRS = {
    "_artifact_launcher": attr.label(
        cfg = "exec",
        default = "@mkosi_debian_tools//:launcher",
        executable = True,
    ),
    "_artifact_tools": attr.label_list(
        cfg = "exec",
        default = ["//mkosi/private:" + script for script in ARTIFACT_TOOL_SCRIPTS],
        allow_files = True,
    ),
    "_input_version": attr.label(
        cfg = "exec",
        default = "//mkosi/private:input_version.py",
        allow_single_file = True,
    ),
}

# Bazel stages a declared symlink, such as one of a Python virtual environment, with its target text, which may resolve
# only in a runfiles tree; like Bazel, the version identifies it by that text.
def _regular_path(file):
    return None if file.is_symlink else file.path

def _declared_symlink_path(file):
    return file.path if file.is_symlink else None

def _hashed_path_arguments(ctx, hashed):
    """Returns param-file Args listing the hashed files and, separately, the declared symlinks among them."""
    arguments = []
    for option, map_each in (("--inputs-file", _regular_path), ("--symlinks-file", _declared_symlink_path)):
        paths = ctx.actions.args()
        paths.use_param_file(option + "=%s", use_always = True)
        paths.set_param_file_format("multiline")
        paths.add_all(hashed, expand_directories = False, map_each = map_each)
        arguments.append(paths)
    return arguments

def _artifact_tool_files(ctx):
    launcher = ctx.attr._artifact_launcher[DefaultInfo]
    return depset(ctx.files._artifact_tools, transitive = [launcher.files, launcher.default_runfiles.files])

def derive_image_version(ctx, action, image_version_file, input_digest, version_inputs):
    """Registers the action that derives the image version from an mkosi build action.

    The derived action reads the same inputs depset as the build action, and the same Args objects form the command
    line that it hashes, so the version covers every input, toolchain file, argument and variable of the build by
    construction. It also hashes version_inputs and the ruleset tools that turn the image into shipped artifacts. The
    build action must read image_version_file in addition to action.inputs.

    Args:
      ctx: Rule context with INPUT_VERSION_ATTRS and IMAGE_METADATA_ATTRS.
      action: Struct returned by mkosi_action for the image build.
      image_version_file: Output file receiving the version and one newline.
      input_digest: Output file receiving the full lowercase hex SHA-256 and one newline.
      version_inputs: Files that the version covers although the build does not read them.
    """
    options = ctx.actions.args()
    options.add(ctx.file._input_version)
    options.add("--environment-json", json.encode(action.env))
    options.add("--execution-requirements-json", json.encode(action.execution_requirements))
    options.add("--version-output", image_version_file)
    options.add("--digest-output", input_digest)
    hashed = depset(version_inputs, transitive = [action.inputs, action.tool_files, _artifact_tool_files(ctx)])
    command_line = ctx.actions.args()
    command_line.add("--command-line")
    command_line.add(action.executable)
    run_python(
        ctx,
        arguments = [options] + _hashed_path_arguments(ctx, hashed) + [command_line] + action.arguments,
        inputs = [ctx.file._input_version, ctx.file._file_hashing, ctx.file._sibling_loader],
        transitive_inputs = [mkosi_toolchain_info(ctx).python_runtime_files, hashed],
        outputs = [image_version_file, input_digest],
        execution_requirements = mkosi_execution_requirements(True, offline = True),
        mnemonic = "MkosiInputVersion",
        progress_message = "Deriving the image version of %{label} from its inputs",
    )

def check_version_inputs(image, files, consumer):
    """Fails unless a version derived from the image's inputs covers files that consumer ships with the image.

    Signing certificates and Secure Boot keys change the shipped bytes after the version is fixed, so an image with
    image_version_from_inputs must declare them in version_inputs. Images with another kind of version pass.

    Args:
      image: MkosiImageInfo of the image.
      files: Files that consumer adds to the image's shipped bytes; None entries are ignored.
      consumer: Description of the consuming rule and attribute for the error message.
    """
    if getattr(image, "input_digest", None) == None:
        return
    declared = getattr(image, "version_inputs", None) or []
    missing = [file.short_path for file in files if file != None and file not in declared]
    if missing:
        fail(("%s changes the shipped bytes of an image whose version is derived from its inputs; add %s to the " +
              "image's version_inputs so that a change gives a new version") % (consumer, ", ".join(missing)))
