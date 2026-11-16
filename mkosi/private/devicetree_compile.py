"""Compiles a device tree source, or takes a compiled device tree, and applies overlays, with the pinned Debian tools.

Like the Linux kernel's build, it preprocesses each source with `cpp -nostdinc -undef -x assembler-with-cpp`, so that
sources can include headers such as dt-bindings and use macros, and compiles it with `dtc`. `fdtoverlay` then applies
the overlays in order. Every tool runs in one call of the Debian tools launcher, on copies of the inputs in a scratch
directory next to the output, which is removed afterwards.
"""

import argparse
import os
import runpy
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
devicetree = _load_sibling(__file__, "devicetree")
launcher_tool = _load_sibling(__file__, "launcher_tool")

_CPP = "/usr/bin/cpp -nostdinc -undef -x assembler-with-cpp -D__DTS__"
_COMPILED = (".dtb", ".dtbo")


@dataclass(frozen=True)
class Sources:
    """The inputs of a device tree, as paths relative to the working directory.

    Attributes:
        source: The .dts to compile, or a compiled .dtb.
        files: Files that the sources may include.
        overlays: Overlay sources or compiled .dtbo files, applied in order.
        include_directories: Directories that #include <...> and /include/ search.
        defines: Preprocessor definitions, NAME or NAME=VALUE.
    """

    source: str
    files: Sequence[str] = ()
    overlays: Sequence[str] = ()
    include_directories: Sequence[str] = ()
    defines: Sequence[str] = ()


def compile_script(scratch: str, sources: Sources) -> str:
    """Returns the shell script that builds scratch/out.dtb in the launcher's namespace.

    scratch is the namespace path of the scratch directory, whose src directory holds copies of the sources.
    """
    copies = scratch + "/src/"
    cpp_options = [
        *("-I" + copies + directory for directory in sources.include_directories),
        *("-D" + define for define in sources.defines),
    ]
    dtc_options = ["-i" + copies + directory for directory in sources.include_directories]
    lines = ["set -eu", "export SOURCE_DATE_EPOCH=0"]

    def compiled(path: str, output: str, options: Sequence[str]) -> str:
        if path.endswith(_COMPILED):
            return shlex.quote(copies + path)
        preprocessed = output + ".pre"
        lines.append(" ".join([_CPP, *map(shlex.quote, [*cpp_options, "-o", preprocessed, copies + path])]))
        dtc = ["/usr/bin/dtc", "-I", "dts", "-O", "dtb", *options, *dtc_options, "-o", output, preprocessed]
        lines.append(" ".join(map(shlex.quote, dtc)))
        return shlex.quote(output)

    # Overlays can only refer to the base's labels if it has a __symbols__ node.
    base = compiled(sources.source, scratch + "/base.dtb", ["-@"] if sources.overlays else [])
    applied = [
        compiled(overlay, "{}/overlay-{}.dtbo".format(scratch, index), ["-@"])
        for index, overlay in enumerate(sources.overlays)
    ]
    output = shlex.quote(scratch + "/out.dtb")
    if applied:
        lines.append(" ".join(["/usr/bin/fdtoverlay", "-i", base, "-o", output, *applied]))
    else:
        lines.append(" ".join(["/bin/cp", base, output]))
    return "\n".join(lines) + "\n"


def build_device_tree(launcher: str, sources: Sources, output: Path) -> None:
    """Builds output from sources with the Debian tools launcher.

    Raises SystemExit if a tool fails or the result is not a device tree with a root compatible string.
    """
    scratch = Path(os.fspath(output) + ".scratch")
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        for path in dict.fromkeys([sources.source, *sources.files, *sources.overlays]):
            copy = scratch / "src" / path
            copy.parent.mkdir(parents=True, exist_ok=True)
            # The launcher's namespace cannot follow the symlinks of a sandboxed input.
            shutil.copyfile(path, copy)
        script = compile_script(launcher_tool.namespace_path(launcher, scratch), sources)
        try:
            launcher_tool.run_tool(launcher, "/bin/sh", "-c", script)
        except OSError as error:
            raise SystemExit("devicetree: cannot run the Debian tools: {}".format(error)) from error
        except subprocess.CalledProcessError as error:
            message = "devicetree: building {} failed with status {}".format(sources.source, error.returncode)
            raise SystemExit(message) from error
        built = (scratch / "out.dtb").read_bytes()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    try:
        tree = devicetree.parse_device_tree(built)
    except devicetree.DeviceTreeError as error:
        raise SystemExit("devicetree: {}: {}".format(sources.source, error)) from error
    if not tree.compatible:
        raise SystemExit("devicetree: {}: the root node has no compatible string".format(sources.source))
    output.write_bytes(built[: tree.size])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", required=True)
    parser.add_argument("--src", required=True)
    parser.add_argument("--file", action="append", default=[], help="A file that sources may include.")
    parser.add_argument("--overlay", action="append", default=[])
    parser.add_argument("--include-directory", action="append", default=[])
    parser.add_argument("--define", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    sources = Sources(arguments.src, arguments.file, arguments.overlay, arguments.include_directory, arguments.define)
    build_device_tree(arguments.launcher, sources, arguments.output)


if __name__ == "__main__":
    main()
