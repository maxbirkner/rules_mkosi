#!/usr/bin/python3
"""Run mkosi after resolving Bazel paths before mkosi changes directory."""

import importlib.util
import os
import runpy
import subprocess
import sys
import traceback
from pathlib import Path

sys.dont_write_bytecode = True

_RELEASE_CHILD_VARIABLE = "RULES_MKOSI_RELEASE_CHILD"
_RELEASE_PARENT_OPTIONS = ("--debian-snapshot-repository", "--release-base-tree")


def _load_module(name, path, failure):
    """Loads a module from an explicit path, because Bazel declares these files as inputs but not on sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise failure
    module = importlib.util.module_from_spec(spec)
    if spec.submodule_search_locations is not None:
        # The package's relative imports resolve it through sys.modules.
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_sibling(name, filename, description):
    path = Path(__file__).parent / filename
    return _load_module(name, path, RuntimeError("{} cannot be loaded: {}".format(description, path)))


diagnostics = _load_sibling("mkosi_diagnostics", "diagnostics.py", "diagnostic formatter")
_package = _load_sibling("rules_mkosi_runner", "mkosi_runner/__init__.py", "run_mkosi package")
command_line = _package.command_line
release_patches = _package.release_patches
release_sandbox = _package.release_sandbox
release_validation = _package.release_validation
tree = _package.tree


def _image_version_from_file(path, slot_label_image_id=None):
    """Returns the validated version in path using the sibling image_version.py helper."""
    module = _load_sibling("rules_mkosi_image_version", "image_version.py", "image version helper")
    try:
        return module.read_image_version(path, slot_label_image_id)
    except (OSError, ValueError) as error:
        raise SystemExit("IMAGE_VERSION_INVALID: {}".format(error)) from None


def _run_mkosi(script, arguments, runner=subprocess.run, environment=None):
    """Run mkosi and classify process-boundary failures without masking exit status."""
    options = {"check": False, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if environment is not None:
        options["env"] = environment
    try:
        completed = runner([sys.executable, script] + arguments, **options)
    except OSError as error:
        diagnostics.fail("TOOLCHAIN_FAILURE", "mkosi executable cannot start {}: {}".format(script, error))
    if completed.returncode:
        _fail_mkosi(completed)
    _forward_output(completed)


def _fail_mkosi(completed):
    original = completed.stdout + completed.stderr
    tail = original.decode(errors="replace").strip().splitlines()[-8:]
    diagnostics.fail(
        diagnostics.classify_mkosi_output(original),
        "mkosi image assembly exited with status {}: {}".format(completed.returncode, " | ".join(tail)),
        original,
        exit_code=diagnostics.child_exit_code(completed.returncode),
    )


def _forward_output(completed):
    for stream, content in ((sys.stdout, completed.stdout), (sys.stderr, completed.stderr)):
        binary_stream = getattr(stream, "buffer", None)
        if binary_stream is None:
            stream.write(content.decode(errors="replace"))
        else:
            binary_stream.write(content)


def _run_release_parent(argv):
    """Runs a release build in a child process that patches mkosi, and publishes the child's outputs.

    The child runs mkosi in-process, so the parent classifies its failures like those of any other mkosi run.
    """
    preamble_arguments = argv[1:]
    # Reject an invalid version before the release child starts, so that the failure is not reported as an mkosi
    # assembly failure.
    image_version_file = command_line.preamble_value(preamble_arguments, "--image-version-file")
    if image_version_file is not None:
        slot_label_image_id = command_line.preamble_value(preamble_arguments, "--slot-label-image-id")
        _image_version_from_file(image_version_file, slot_label_image_id)
    _run_mkosi(os.path.abspath(__file__), argv, environment={**os.environ, _RELEASE_CHILD_VARIABLE: "1"})
    base_initrd_output = command_line.preamble_value(preamble_arguments, "--release-base-initrd-output")
    if base_initrd_output is not None:
        output_directory = command_line.mkosi_option_value(preamble_arguments, "--output-directory")
        _publish_base_initrd(output_directory, base_initrd_output)


def _publish_base_initrd(output_directory, destination):
    """Moves mkosi's default initrd, which it names through a relative symlink, to the declared output."""
    link = Path(output_directory) / "initrd"
    if not link.is_symlink():
        raise SystemExit("mkosi did not produce the default initrd link {}".format(link))
    source = link.resolve(strict=True)
    if source.parent != Path(output_directory).resolve() or not source.is_file():
        raise SystemExit("mkosi default initrd {} is not a file in the output directory".format(source))
    link.unlink()
    os.replace(source, destination)


def _absolutize_python_path():
    """Makes PYTHONPATH entries absolute, so that they stay valid after mkosi changes its working directory."""
    if not os.environ.get("PYTHONPATH"):
        return
    python_paths = os.environ["PYTHONPATH"].split(os.pathsep)
    os.environ["PYTHONPATH"] = os.pathsep.join(os.path.abspath(path or ".") for path in python_paths)
    sys.path[:] = [os.path.abspath(path) if path in python_paths else path for path in sys.path]


def _mkosi_arguments(preamble, mkosi_arguments):
    arguments = command_line.absolute_paths(mkosi_arguments)
    if preamble.image_version_file is None:
        return arguments
    image_version = _image_version_from_file(preamble.image_version_file, preamble.slot_label_image_id)
    return command_line.with_image_version(arguments, image_version)


def _release_stage(preamble):
    """Rejects partial option groups and returns the release stage, or None for a tracer build."""
    debian_tools = preamble.debian_tools_options()
    if any(debian_tools) and not all(debian_tools):
        raise SystemExit("incomplete Debian tools archive configuration")
    release = [option is not None for option in preamble.release_options()]
    if any(release) and not all(release):
        raise SystemExit("incomplete release configuration")
    return command_line.release_stage(
        any(release),
        preamble.debian_snapshot_repository,
        preamble.release_base_tree,
        preamble.release_initrd,
        preamble.release_base_initrd_output,
    )


def _workspace(arguments):
    return Path(command_line.value_after(arguments, "--workspace-directory"))


def _extract_debian_tools(preamble, arguments):
    workspace = _workspace(arguments)
    tools_root = Path(command_line.value_after(arguments, "--tools-tree"))
    if tools_root != workspace / "debian-tools":
        raise SystemExit("Debian tools destination must be inside the mkosi workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    tree.remove_tree(tools_root, "Debian tools destination")
    extractor = _load_module(
        "mkosi_debian_extract_tree",
        preamble.debian_tools_extractor,
        SystemExit("Debian tools extractor cannot be loaded"),
    )
    extractor.extract(preamble.debian_tools_archive, tools_root, preamble.debian_tools_sha256)


def _prepare_release_sandbox(preamble, arguments, stage):
    """Adds the release sandbox, and the Debian snapshot mirror that it returns if the stage installs packages."""
    if preamble.debian_snapshot_repository:
        return release_sandbox.configure_release_mirror(
            preamble.debian_snapshot_repository, _workspace(arguments), arguments
        )
    if stage == "finalize":
        release_sandbox.configure_release_sandbox(_workspace(arguments), arguments)
    return None


def _stage_configuration(preamble, arguments):
    """Points mkosi at a normalized copy of the -C configuration directory and returns that copy, if any."""
    if "-C" not in arguments:
        return None
    directory_index = arguments.index("-C") + 1
    directory = os.fspath(Path(arguments[directory_index]))
    staged = _workspace(arguments) / "staging-root"
    tree.materialize_tree(directory, staged, preamble.executable_paths)
    if preamble.staging_manifest:
        tree.restore_manifest_links(staged, preamble.staging_manifest)
    arguments[directory_index] = os.fspath(staged)
    for index, argument in enumerate(arguments):
        if argument.startswith(directory + os.sep):
            arguments[index] = os.fspath(staged) + argument[len(directory) :]
    return staged


def _release_settings(preamble, stage):
    return release_validation.ReleaseSettings(
        seed=preamble.release_seed,
        source_date_epoch=preamble.release_source_date_epoch,
        distribution=preamble.release_distribution,
        codename=preamble.release_codename,
        snapshot=preamble.release_snapshot,
        firmware=preamble.release_firmware,
        components=preamble.release_components,
        stage=stage,
        base_tree=preamble.release_base_tree,
        base_initrd=preamble.release_initrd,
    )


def _activate_release_mode(preamble, arguments, stage, mirror, staged):
    if staged is None:
        raise SystemExit("a release build requires a staged -C configuration directory")
    if stage == "finalize":
        release_validation.validate_finalize_config_directory(staged)
    extra_tree = staged / "mkosi.extra"
    release_patches.activate_release_mode(
        mirror,
        _release_settings(preamble, stage),
        command_line.declared_paths(arguments),
        extra_tree.resolve() if extra_tree.is_dir() else None,
    )


def _run_mkosi_in_process(script, arguments):
    sys.argv[:] = [script] + arguments
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as error:
        if error.code not in (None, 0):
            print(
                "rules_mkosi release child failed: status={!r}; command={!r}".format(error.code, sys.argv),
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
        raise


def main():
    if len(sys.argv) < 3:
        raise SystemExit(command_line.USAGE)
    release_child = os.environ.get(_RELEASE_CHILD_VARIABLE) == "1"
    if not release_child and any(option in sys.argv[2:] for option in _RELEASE_PARENT_OPTIONS):
        _run_release_parent(sys.argv[1:])
        return
    script = os.path.abspath(sys.argv[1])
    preamble, mkosi_arguments = command_line.parse_preamble(sys.argv[2:])
    _absolutize_python_path()
    arguments = _mkosi_arguments(preamble, mkosi_arguments)
    diagnostics.run_kernel_preflight(preamble.kernel_preflight, "mkosi image assembly")
    stage = _release_stage(preamble)
    if all(preamble.debian_tools_options()):
        _extract_debian_tools(preamble, arguments)
    mirror = _prepare_release_sandbox(preamble, arguments, stage)
    staged = _stage_configuration(preamble, arguments)
    if stage is not None:
        _activate_release_mode(preamble, arguments, stage, mirror, staged)
    if release_child:
        _run_mkosi_in_process(script, arguments)
    else:
        _run_mkosi(script, arguments)


if __name__ == "__main__":
    main()
