"""Derivation of an mkosi_image version from everything that its image build action reads."""

load(":mkosi_action.bzl", "mkosi_execution_requirements")
load(":python_action.bzl", "mkosi_toolchain_info", "run_python")

INPUT_VERSION_ATTRS = {
    "_input_version": attr.label(
        cfg = "exec",
        default = "//mkosi/private:input_version.py",
        allow_single_file = True,
    ),
}

def derive_image_version(ctx, action, image_version_file, input_digest):
    """Registers the action that derives the image version from an mkosi build action.

    The derived action reads the same inputs depset as the build action, and the same Args objects form the command
    line that it hashes, so the version covers every input, toolchain file, argument and variable of the build by
    construction. The build action must read image_version_file in addition to action.inputs.

    Args:
      ctx: Rule context with INPUT_VERSION_ATTRS and IMAGE_METADATA_ATTRS.
      action: Struct returned by mkosi_action for the image build.
      image_version_file: Output file receiving the version and one newline.
      input_digest: Output file receiving the full lowercase hex SHA-256 and one newline.
    """
    options = ctx.actions.args()
    options.add(ctx.file._input_version)
    options.add("--environment-json", json.encode(action.env))
    options.add("--execution-requirements-json", json.encode(action.execution_requirements))
    options.add("--version-output", image_version_file)
    options.add("--digest-output", input_digest)
    hashed = depset(transitive = [action.inputs, action.tool_files])
    inputs = ctx.actions.args()
    inputs.use_param_file("--inputs-file=%s", use_always = True)
    inputs.set_param_file_format("multiline")
    inputs.add_all(hashed, expand_directories = False)
    command_line = ctx.actions.args()
    command_line.add("--command-line")
    command_line.add(action.executable)
    run_python(
        ctx,
        arguments = [options, inputs, command_line] + action.arguments,
        inputs = [ctx.file._input_version, ctx.file._file_hashing, ctx.file._sibling_loader],
        transitive_inputs = [mkosi_toolchain_info(ctx).python_runtime_files, hashed],
        outputs = [image_version_file, input_digest],
        execution_requirements = mkosi_execution_requirements(True, offline = True),
        mnemonic = "MkosiInputVersion",
        progress_message = "Deriving the image version of %{label} from its inputs",
    )
