"""Builds small, reproducible Debian binary packages for tests, without dpkg-deb."""

import gzip
import importlib
import io
import json
import lzma
import sys
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath


def _compress_zstd(content: bytes) -> bytes:
    # compression.zstd is new in Python 3.14, which the tests run on; mypy checks for Python 3.10.
    compressed: bytes = importlib.import_module("compression.zstd").compress(content)
    return compressed


_COMPRESSORS = {
    "none": ("", lambda content: content),
    "gz": (".gz", lambda content: gzip.compress(content, mtime=0)),
    "xz": (".xz", lzma.compress),
    "zst": (".zst", _compress_zstd),
}


def _add_entry(archive: tarfile.TarFile, name: str, content: bytes | None, mode: int) -> None:
    info = tarfile.TarInfo(name)
    info.mode = mode
    info.uname = info.gname = "root"
    if content is None:
        info.type = tarfile.DIRTYPE
        archive.addfile(info)
        return
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))


def _tar(entries: Sequence[tuple[str, bytes | None, int]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name, content, mode in entries:
            _add_entry(archive, name, content, mode)
    return output.getvalue()


def _data_entries(files: Mapping[str, str]) -> list[tuple[str, bytes | None, int]]:
    directories: set[str] = set()
    for path in files:
        directories.update("./" + str(parent) for parent in PurePosixPath(path.lstrip("/")).parents[:-1])
    entries: list[tuple[str, bytes | None, int]] = [(directory, None, 0o755) for directory in directories]
    entries += [("./" + path.lstrip("/"), content.encode(), 0o644) for path, content in files.items()]
    return sorted(entries, key=lambda entry: entry[0])


def _ar_member(name: str, content: bytes) -> bytes:
    header = "{:<16}{:<12}{:<6}{:<6}{:<8}{:<10}`\n".format(name, 0, 0, 0, 100644, len(content)).encode("ascii")
    return header + content + (b"\n" if len(content) % 2 else b"")


def build_deb(
    control: Sequence[tuple[str, str]],
    files: Mapping[str, str],
    scripts: Mapping[str, str] | None = None,
    compression: str = "xz",
) -> bytes:
    """Returns a .deb with the control fields, the files keyed by absolute path, and maintainer scripts.

    Every member is owned by root with a zero timestamp, so equal arguments give equal bytes.
    """
    suffix, compress = _COMPRESSORS[compression]
    control_text = "".join("{}: {}\n".format(field, value) for field, value in control)
    control_entries: list[tuple[str, bytes | None, int]] = [("./control", control_text.encode(), 0o644)]
    control_entries += [("./" + name, text.encode(), 0o755) for name, text in sorted((scripts or {}).items())]
    return (
        b"!<arch>\n"
        + _ar_member("debian-binary", b"2.0\n")
        + _ar_member("control.tar" + suffix, compress(_tar([(".", None, 0o755), *control_entries])))
        + _ar_member("data.tar" + suffix, compress(_tar([(".", None, 0o755), *_data_entries(files)])))
    )


def main(argv: Sequence[str]) -> None:
    """Writes the .deb that the JSON specification argv[0] describes to argv[1]."""
    specification_path, output_path = argv
    with open(specification_path) as source:
        specification = json.load(source)
    package = build_deb(
        [(field, value) for field, value in specification["control"]],
        specification["files"],
        specification.get("scripts"),
    )
    with open(output_path, "wb") as output:
        output.write(package)


if __name__ == "__main__":
    main(sys.argv[1:])
