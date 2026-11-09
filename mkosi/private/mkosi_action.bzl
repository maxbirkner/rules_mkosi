"""mkosi command line and build action shared by mkosi_base and mkosi_image."""

load(":python_action.bzl", "mkosi_toolchain_info", "python_action")

DEBIAN_TOOLS_TOOLCHAIN_TYPE = "//mkosi/toolchain:debian_tools_toolchain_type"

MKOSI_BUILD_TOOLCHAINS = [
    "//mkosi/toolchain:toolchain_type",
    DEBIAN_TOOLS_TOOLCHAIN_TYPE,
]

MKOSI_BUILD_EXEC_CONSTRAINTS = [
    "@platforms//os:linux",
    "@platforms//cpu:x86_64",
]

MKOSI_BUILD_ATTRS = {
    "_diagnostics": attr.label(
        cfg = "exec",
        default = "//mkosi/private:diagnostics.py",
        allow_single_file = True,
    ),
    "_kernel_preflight": attr.label(
        cfg = "exec",
        default = "//mkosi/private:kernel_preflight",
        executable = True,
    ),
    "_run_script": attr.label(
        cfg = "exec",
        default = "//mkosi/private:run_mkosi.py",
        allow_single_file = True,
    ),
    "_run_script_modules": attr.label(
        cfg = "exec",
        default = "//mkosi/private:run_mkosi_modules",
        allow_files = True,
    ),
    "_stage_script": attr.label(
        cfg = "exec",
        default = "//mkosi/private:stage_inputs.py",
        allow_single_file = True,
    ),
}

def pefile_root(mkosi):
    """Returns the directory that contains the pefile module of the mkosi toolchain."""
    return mkosi.pefile.path[:-len("/pefile.py")]

def mkosi_execution_requirements(release_mode, offline):
    """Returns the execution requirements of an mkosi action.

    Args:
      release_mode: Whether the action is a hermetic release build, whose outputs may be cached.
      offline: Whether the action installs packages only from declared inputs, so that it runs without network.

    Returns:
      Execution requirements dict.
    """
    requirements = {"no-remote-exec": "1"}
    requirements["block-network" if offline else "requires-network"] = "1"
    if not release_mode:
        requirements["no-cache"] = "1"
    return requirements

def mkosi_arguments(ctx):
    """Returns new arguments that start the mkosi runner with the resolved toolchains.

    Args:
      ctx: Rule context with MKOSI_BUILD_ATTRS and MKOSI_BUILD_TOOLCHAINS.

    Returns:
      Args for run_mkosi.
    """
    mkosi = mkosi_toolchain_info(ctx)
    debian_tools = ctx.toolchains[DEBIAN_TOOLS_TOOLCHAIN_TYPE].debian_tools
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
    return arguments

def add_snapshot_arguments(arguments, snapshot, repository):
    """Adds the runner options that describe the Debian snapshot of a build.

    Args:
      arguments: Args of the mkosi runner.
      snapshot: DebianSnapshotInfo of the build.
      repository: Whether the build installs packages from the snapshot repository instead of the network.
    """
    if repository:
        arguments.add("--debian-snapshot-repository")
        arguments.add(snapshot.repository.path)
    arguments.add("--debian-snapshot-components")
    arguments.add(",".join(snapshot.components))

def add_release_arguments(arguments, release, firmware):
    """Adds the runner options that pin a release build to its Debian snapshot and reproducibility settings.

    Args:
      arguments: Args of the mkosi runner.
      release: Struct with the DebianSnapshotInfo `snapshot`, `seed` and `source_date_epoch`.
      firmware: Firmware tier of the release.
    """
    snapshot = release.snapshot
    arguments.add("--release-seed")
    arguments.add(release.seed)
    arguments.add("--release-source-date-epoch")
    arguments.add(release.source_date_epoch)
    arguments.add("--release-distribution")
    arguments.add(snapshot.distribution)
    arguments.add("--release-codename")
    arguments.add(snapshot.codename)
    arguments.add("--release-snapshot")
    arguments.add(snapshot.snapshot)
    arguments.add("--release-firmware")
    arguments.add(firmware)

def add_staging_arguments(arguments, executable_paths, staging):
    """Adds the runner options that describe the staged inputs.

    Args:
      arguments: Args of the mkosi runner.
      executable_paths: Staged paths that must keep their executable mode.
      staging: Staged inputs of stage_inputs, or None.
    """
    for path in executable_paths:
        arguments.add("--executable-path")
        arguments.add(path)
    if staging:
        arguments.add("--staging-manifest")
        arguments.add(staging.manifest.path)

def add_output_arguments(arguments, ctx, workspace, output_format, split_artifacts):
    """Adds the mkosi options for the Debian tools tree and the output format.

    Args:
      arguments: Args of the mkosi runner.
      ctx: Rule context with MKOSI_BUILD_TOOLCHAINS.
      workspace: Workspace directory of the build.
      output_format: mkosi Format=, either disk or tar.
      split_artifacts: mkosi SplitArtifacts= value.
    """
    arguments.add("--tools-tree")
    arguments.add(workspace + "/debian-tools")
    arguments.add("--extra-search-path")
    arguments.add(pefile_root(mkosi_toolchain_info(ctx)))
    arguments.add("--format=" + output_format)
    arguments.add("--output-extension=" + ("raw" if output_format == "disk" else output_format))
    arguments.add("--compress-output=none")
    arguments.add("--split-artifacts=" + split_artifacts)

def add_build_arguments(arguments, output_directory, output_name, workspace, build_sources, debug):
    """Adds the mkosi output and workspace directories followed by the build verb.

    Args:
      arguments: Args of the mkosi runner.
      output_directory: Directory receiving the mkosi outputs.
      output_name: mkosi Output= name.
      workspace: Directory for the workspace, caches and build directory.
      build_sources: Whether mkosi keeps the configured BuildSources=.
      debug: Whether mkosi logs debug output.
    """
    arguments.add("--output-directory")
    arguments.add(output_directory)
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
    if not build_sources:
        arguments.add("--build-sources=")
    arguments.add("--no-pager")
    if debug:
        arguments.add("--debug")
    arguments.add("build")

def mkosi_tool_inputs(ctx):
    """Returns the runner, mkosi and Debian tools files read by every mkosi build."""
    mkosi = mkosi_toolchain_info(ctx)
    debian_tools = ctx.toolchains[DEBIAN_TOOLS_TOOLCHAIN_TYPE].debian_tools
    return [
        mkosi.script,
        ctx.file._run_script,
        ctx.file._diagnostics,
        ctx.executable._kernel_preflight,
        mkosi.pefile,
        debian_tools.tree,
        debian_tools.extractor,
    ] + ctx.files._run_script_modules

def _mkosi_environment(mkosi, release):
    mkosi_root = mkosi.script.path[:-len("/mkosi/__main__.py")]
    environment = {
        # mkosi would otherwise first ask the host's systemd-nsresourced for a user namespace, so the namespace setup
        # would depend on the build host. The unprivileged user namespace it falls back to is the one that
        # kernel_preflight checks.
        "MKOSI_FORCE_USERNS_FALLBACK": "1",
        "PYTHONPATH": mkosi_root + ":" + pefile_root(mkosi),
    }
    if release:
        environment.update({
            "MKOSI_HOST_DISTRIBUTION": release.snapshot.distribution,
            "MKOSI_HOST_RELEASE": release.snapshot.codename,
            "SOURCE_DATE_EPOCH": str(release.source_date_epoch),
        })
    return environment

def mkosi_action(ctx, arguments, inputs, release, offline):
    """Describes an mkosi build action without registering it.

    Args:
      ctx: Rule context with MKOSI_BUILD_ATTRS and MKOSI_BUILD_TOOLCHAINS.
      arguments: Args of the mkosi runner.
      inputs: Files read by the build, including mkosi_tool_inputs.
      release: Release struct of add_release_arguments, or None for a tracer build.
      offline: Whether the build installs packages only from a Debian snapshot or a base, without network.

    Returns:
      Struct with the executable, arguments, inputs, tools, env and execution_requirements of the action, and
      tool_files, the depset of every file that its tools read, including their runfiles.
    """
    mkosi = mkosi_toolchain_info(ctx)
    kernel_preflight = ctx.attr._kernel_preflight[DefaultInfo]
    action = python_action(
        ctx,
        arguments = [arguments],
        inputs = inputs,
        transitive_inputs = [mkosi.runfiles_files, mkosi.python_runtime_files],
        tools = [kernel_preflight.files_to_run],
        env = _mkosi_environment(mkosi, release),
    )
    return struct(
        executable = action.executable,
        arguments = action.arguments,
        inputs = action.inputs,
        tools = action.tools,
        env = action.env,
        execution_requirements = mkosi_execution_requirements(release != None, offline),
        tool_files = depset(
            [action.executable],
            transitive = [mkosi.python_runtime_files, kernel_preflight.default_runfiles.files],
        ),
    )

def register_mkosi_action(ctx, action, outputs, mnemonic, progress_message, extra_inputs = []):
    """Registers an mkosi build action described by mkosi_action.

    Args:
      ctx: Rule context with MKOSI_BUILD_ATTRS and MKOSI_BUILD_TOOLCHAINS.
      action: Struct returned by mkosi_action.
      outputs: Files written by the build.
      mnemonic: Action mnemonic.
      progress_message: Action progress message.
      extra_inputs: Files read by the build in addition to action.inputs.
    """
    ctx.actions.run(
        executable = action.executable,
        arguments = action.arguments,
        inputs = depset(extra_inputs, transitive = [action.inputs]) if extra_inputs else action.inputs,
        tools = action.tools,
        outputs = outputs,
        env = action.env,
        execution_requirements = action.execution_requirements,
        mnemonic = mnemonic,
        progress_message = progress_message,
    )

def run_mkosi(ctx, arguments, inputs, outputs, release, offline, mnemonic, progress_message):
    """Registers an mkosi build action.

    Args:
      ctx: Rule context with MKOSI_BUILD_ATTRS and MKOSI_BUILD_TOOLCHAINS.
      arguments: Args of the mkosi runner.
      inputs: Files read by the build, including mkosi_tool_inputs.
      outputs: Files written by the build.
      release: Release struct of add_release_arguments, or None for a tracer build.
      offline: Whether the build installs packages only from a Debian snapshot or a base, without network.
      mnemonic: Action mnemonic.
      progress_message: Action progress message.
    """
    register_mkosi_action(ctx, mkosi_action(ctx, arguments, inputs, release, offline), outputs, mnemonic, progress_message)
