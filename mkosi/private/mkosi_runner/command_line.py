"""Parses the run_mkosi.py preamble and rewrites the mkosi arguments that follow it."""

import os
from dataclasses import dataclass, field

from . import mkosi_options

USAGE = "usage: run_mkosi.py MKOSI_SCRIPT [--executable-path PATH] -- [mkosi arguments]"


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
    debian_snapshot_components: tuple[str, ...] | None = None
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
        )


def _source_date_epoch(value):
    try:
        return int(value)
    except ValueError as error:
        raise SystemExit("release source date epoch must be an integer") from error


def _snapshot_components(value):
    components = tuple(value.split(","))
    if "main" not in components or "" in components:
        raise SystemExit("Debian snapshot components must be a comma-separated list including main")
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
    "--debian-snapshot-components": ("debian_snapshot_components", _snapshot_components),
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
    """Returns the value of a run_mkosi.py preamble option, or None.

    The preamble consists of option and value pairs up to the first --, so the mkosi arguments after it are ignored.
    """
    for index in range(0, len(argv) - 1, 2):
        if argv[index] == "--":
            break
        if argv[index] == option:
            return argv[index + 1]
    return None


def mkosi_option_value(argv, option):
    """Returns the value of the mkosi option, in any spelling, in the mkosi arguments after the preamble's --."""
    arguments = argv[argv.index("--") + 1 :]
    values = [occurrence.value for occurrence in _occurrences_of(arguments, option)]
    if len(values) != 1 or values[0] is None:
        raise SystemExit("expected exactly one mkosi {} argument".format(option))
    return values[0]


def value_after(arguments, option):
    """Returns the value of the last occurrence of the mkosi option, in any spelling, as mkosi reads it."""
    values = [occurrence.value for occurrence in _occurrences_of(arguments, option)]
    if not values or values[-1] is None:
        raise SystemExit("mkosi {} argument is missing".format(option))
    return values[-1]


def _occurrences_of(arguments, option):
    dest = mkosi_options.option(option).dest
    return [occurrence for occurrence in mkosi_options.occurrences(arguments) if occurrence.option.dest == dest]


def configuration_directory(arguments):
    """Returns the Occurrence of the -C/--directory option that mkosi uses, which is the last one, or None."""
    directories = [
        occurrence
        for occurrence in mkosi_options.occurrences(arguments)
        if occurrence.option.dest == mkosi_options.DIRECTORY
    ]
    if directories and directories[-1].value is None:
        raise SystemExit("mkosi path option is missing its value")
    return directories[-1] if directories else None


def path_occurrences(arguments):
    """Returns the Occurrences of mkosi options whose values are paths, and rejects a missing value."""
    found = [occurrence for occurrence in mkosi_options.occurrences(arguments) if occurrence.option.path]
    if any(occurrence.value is None for occurrence in found):
        raise SystemExit("mkosi path option is missing its value")
    return found


def absolute_paths(arguments):
    """Resolves mkosi path option values now, because mkosi changes its working directory before it reads them."""
    result = list(arguments)
    for occurrence in path_occurrences(result):
        occurrence.replace(result, occurrence.option.map_paths(occurrence.value, os.path.abspath))
    return result


def declared_paths(arguments):
    """Returns the paths of the mkosi path options, which are the inputs that a release build may read."""
    return [
        path
        for occurrence in path_occurrences(arguments)
        for path in occurrence.option.declared_paths(occurrence.value)
    ]


def with_image_version(arguments, image_version):
    """Passes image_version to mkosi next to the --image-id= option that it qualifies."""
    image_ids = [index for index, argument in enumerate(arguments) if argument.startswith("--image-id=")]
    if len(image_ids) != 1:
        raise SystemExit("--image-version-file requires exactly one --image-id= mkosi argument")
    insert_at = image_ids[0] + 1
    return [*arguments[:insert_at], "--image-version=" + image_version, *arguments[insert_at:]]


def release_stage(release, debian_snapshot_repository, base_tree, initrd, base_initrd_output):
    """Returns image, base, finalize, or None for a tracer build, and rejects inconsistent options.

    A tracer build may install packages from the Debian snapshot repository, like the image stage of a release.
    """
    stage = _requested_release_stage(debian_snapshot_repository, base_tree, initrd, base_initrd_output)
    if (stage is not None) != release and stage != "image":
        raise SystemExit("incomplete release configuration")
    return stage if release else None


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
