"""Parses the run_mkosi.py preamble and rewrites the mkosi arguments that follow it."""

import os
from dataclasses import dataclass, field

USAGE = "usage: run_mkosi.py MKOSI_SCRIPT [--executable-path PATH] -- [mkosi arguments]"

PATH_OPTIONS = frozenset(
    {
        "-I",
        "--include",
        "-C",
        "--directory",
        "--tools-tree",
        "--extra-search-path",
        "--output-directory",
        "--workspace-directory",
        "--cache-directory",
        "--package-cache-directory",
        "--build-directory",
        "--sandbox-tree",
        "--repart-directory",
        "--base-tree",
        "--initrd",
    }
)

# mkosi constants accepted in place of a path; they are not resolved against the working directory.
PATH_CONSTANTS = {"--initrd": ("default",)}


@dataclass
class Preamble:
    """The run_mkosi.py options before the -- that starts the mkosi arguments."""

    executable_paths: list[str] = field(default_factory=list)
    staging_manifest: str | None = None
    debian_tools_archive: str | None = None
    debian_tools_extractor: str | None = None
    debian_tools_sha256: str | None = None
    kernel_preflight: str | None = None
    debian_snapshot_repository: str | None = None
    release_seed: str | None = None
    release_source_date_epoch: int | None = None
    release_distribution: str | None = None
    release_codename: str | None = None
    release_snapshot: str | None = None
    release_firmware: str | None = None
    release_components: tuple[str, ...] | None = None
    image_version_file: str | None = None
    slot_label_image_id: str | None = None
    release_base_tree: str | None = None
    release_initrd: str | None = None
    release_base_initrd_output: str | None = None

    def debian_tools_options(self):
        return (self.debian_tools_archive, self.debian_tools_extractor, self.debian_tools_sha256)

    def release_options(self):
        return (
            self.release_seed,
            self.release_source_date_epoch,
            self.release_distribution,
            self.release_codename,
            self.release_snapshot,
            self.release_firmware,
            self.release_components,
        )


def _source_date_epoch(value):
    try:
        return int(value)
    except ValueError as error:
        raise SystemExit("release source date epoch must be an integer") from error


def _release_components(value):
    components = tuple(value.split(","))
    if "main" not in components or "" in components:
        raise SystemExit("release components must be a comma-separated list including main")
    return components


def _verbatim(value):
    return value


_EXECUTABLE_PATH_OPTION = "--executable-path"

_PREAMBLE_OPTIONS = {
    "--staging-manifest": ("staging_manifest", os.path.abspath),
    "--debian-tools-archive": ("debian_tools_archive", os.path.abspath),
    "--debian-tools-extractor": ("debian_tools_extractor", os.path.abspath),
    "--debian-tools-sha256": ("debian_tools_sha256", _verbatim),
    "--kernel-preflight": ("kernel_preflight", os.path.abspath),
    "--debian-snapshot-repository": ("debian_snapshot_repository", os.path.abspath),
    "--release-seed": ("release_seed", _verbatim),
    "--release-source-date-epoch": ("release_source_date_epoch", _source_date_epoch),
    "--release-distribution": ("release_distribution", _verbatim),
    "--release-codename": ("release_codename", _verbatim),
    "--release-snapshot": ("release_snapshot", _verbatim),
    "--release-firmware": ("release_firmware", _verbatim),
    "--image-version-file": ("image_version_file", os.path.abspath),
    "--slot-label-image-id": ("slot_label_image_id", _verbatim),
    "--release-base-tree": ("release_base_tree", os.path.abspath),
    "--release-initrd": ("release_initrd", os.path.abspath),
    "--release-base-initrd-output": ("release_base_initrd_output", os.path.abspath),
    "--release-components": ("release_components", _release_components),
}


def parse_preamble(argv):
    """Returns the Preamble before the first -- in argv and the mkosi arguments after it."""
    preamble = Preamble()
    index = 0
    while index < len(argv) and argv[index] != "--":
        _apply_preamble_option(preamble, argv, index)
        index += 2
    if index == len(argv):
        raise SystemExit("run_mkosi.py preamble is missing --")
    if not preamble.kernel_preflight:
        raise SystemExit("run_mkosi.py requires --kernel-preflight")
    return preamble, argv[index + 1 :]


def _apply_preamble_option(preamble, argv, index):
    option = argv[index]
    known = option == _EXECUTABLE_PATH_OPTION or option in _PREAMBLE_OPTIONS
    if not known or index + 1 == len(argv):
        raise SystemExit("invalid run_mkosi.py preamble")
    value = argv[index + 1]
    if option == _EXECUTABLE_PATH_OPTION:
        preamble.executable_paths.append(value)
    else:
        name, convert = _PREAMBLE_OPTIONS[option]
        setattr(preamble, name, convert(value))


def preamble_value(argv, option):
    """Returns the value of a run_mkosi.py preamble option, or None."""
    for index, argument in enumerate(argv[:-1]):
        if argument == "--":
            break
        if argument == option:
            return argv[index + 1]
    return None


def mkosi_option_value(argv, option):
    """Returns the value of a separate-argument mkosi option after the preamble."""
    arguments = argv[argv.index("--") + 1 :]
    indices = [index for index, argument in enumerate(arguments[:-1]) if argument == option]
    if len(indices) != 1:
        raise SystemExit("expected exactly one mkosi {} argument".format(option))
    return arguments[indices[0] + 1]


def value_after(arguments, option):
    """Returns the argument after the first occurrence of option."""
    return arguments[arguments.index(option) + 1]


def absolute_paths(arguments):
    """Resolves mkosi path option values now, because mkosi changes its working directory before it reads them."""
    result = []
    pending_option = None
    for argument in arguments:
        if pending_option:
            result.append(_absolute_value(pending_option, argument))
            pending_option = None
        elif argument in PATH_OPTIONS:
            result.append(argument)
            pending_option = argument
        else:
            result.append(_absolute_assignment(argument))
    if pending_option:
        raise SystemExit("mkosi path option is missing its value")
    return result


def _absolute_value(option, value):
    return value if value in PATH_CONSTANTS.get(option, ()) else os.path.abspath(value)


def _absolute_assignment(argument):
    option, separator, value = argument.partition("=")
    if separator and option in PATH_OPTIONS:
        return option + "=" + _absolute_value(option, value)
    return argument


def declared_paths(arguments):
    """Returns the values of the separate-argument path options, which are the inputs that a release build may read."""
    return [
        value
        for option, value in zip(arguments, arguments[1:])
        if option in PATH_OPTIONS and value not in PATH_CONSTANTS.get(option, ())
    ]


def with_image_version(arguments, image_version):
    """Passes image_version to mkosi next to the --image-id= option that it qualifies."""
    image_ids = [index for index, argument in enumerate(arguments) if argument.startswith("--image-id=")]
    if len(image_ids) != 1:
        raise SystemExit("--image-version-file requires exactly one --image-id= mkosi argument")
    insert_at = image_ids[0] + 1
    return arguments[:insert_at] + ["--image-version=" + image_version] + arguments[insert_at:]


def release_stage(release, debian_snapshot_repository, base_tree, initrd, base_initrd_output):
    """Returns image, base, finalize, or None for a tracer build, and rejects inconsistent options."""
    stage = _requested_release_stage(debian_snapshot_repository, base_tree, initrd, base_initrd_output)
    if (stage is not None) != release:
        raise SystemExit("incomplete release configuration")
    return stage


def _requested_release_stage(debian_snapshot_repository, base_tree, initrd, base_initrd_output):
    if base_tree is not None or initrd is not None:
        if base_tree is None or initrd is None:
            raise SystemExit("release finalization requires both --release-base-tree and --release-initrd")
        if debian_snapshot_repository is not None or base_initrd_output is not None:
            raise SystemExit("release finalization cannot use the Debian snapshot or produce a base")
        return "finalize"
    if debian_snapshot_repository is not None:
        return "base" if base_initrd_output is not None else "image"
    if base_initrd_output is not None:
        raise SystemExit("a release base requires the Debian snapshot repository")
    return None
