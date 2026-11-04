"""Reads the systemd-repart partition definitions of an image the way systemd-repart merges them."""

from pathlib import Path

# Minimize= values that systemd-repart parses as off: the empty value, "off" and the false booleans.
_MINIMIZE_OFF = frozenset(("", "off", "0", "no", "n", "false", "f"))


def unsized_verity_hash_definitions(directories):
    """Returns the definitions of Verity=hash partitions that set neither SizeMinBytes= nor Minimize=.

    systemd-repart 257.13 and newer reserve no default size for a verity partition, and mkosi sizes the disk to the
    partitions' minimum sizes (--size=auto), so such a partition gets one 4 KiB block that its hash tree does not
    fit. SizeMaxBytes= alone does not help: there is no free space for the partition to grow into.
    """
    return [path for path, settings in _definitions(directories) if _is_unsized_verity_hash(settings)]


def _definitions(directories):
    """Yields each effective definition and its [Partition] settings, including '<name>.d/*.conf' drop-ins."""
    directories = [Path(directory) for directory in directories]
    for name, path in sorted(_first_by_name(directories).items()):
        dropins = _first_by_name([directory / (name + ".d") for directory in directories])
        yield path, _partition_settings([path, *(dropins[dropin] for dropin in sorted(dropins))])


def _first_by_name(directories):
    # A file in an earlier directory overrides a file of the same name in a later one.
    files = {}
    for directory in directories:
        for path in sorted(directory.glob("*.conf")) if directory.is_dir() else ():
            if not path.is_dir():
                files.setdefault(path.name, path)
    return files


def _partition_settings(paths):
    settings = {}
    for path in paths:
        section = None
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif section == "Partition" and "=" in line and not line.startswith(("#", ";")):
                key, _, value = line.partition("=")
                settings[key.strip()] = value.strip()
    return settings


def _is_unsized_verity_hash(settings):
    return (
        settings.get("Verity") == "hash"
        and not settings.get("SizeMinBytes")
        and settings.get("Minimize", "").lower() in _MINIMIZE_OFF
    )
