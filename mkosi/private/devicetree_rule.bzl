"""The devicetree rule: compiles device tree sources and applies overlays with the pinned Debian tools."""

load(":mkosi_action.bzl", "DEBIAN_TOOLS_TOOLCHAIN_TYPE", "MKOSI_BUILD_EXEC_CONSTRAINTS", "mkosi_execution_requirements")
load(":python_action.bzl", "run_python", "static_python_interpreter")

def _package_directory(ctx, root, directory):
    parts = [part for part in (root, ctx.label.workspace_root, ctx.label.package, directory) if part and part != "."]
    return "/".join(parts)

def _include_directories(ctx):
    """Returns the include directories, relative to the execution root, in the source and the output trees."""
    directories = []
    for directory in ctx.attr.includes:
        if directory.startswith("/") or ".." in directory.split("/"):
            fail("includes must be directories inside the package, not {}".format(directory))
        directories.append(_package_directory(ctx, "", directory))
        directories.append(_package_directory(ctx, ctx.bin_dir.path, directory))
    return directories

def _validate_defines(defines):
    for define in defines:
        name = define.partition("=")[0]
        if not name or not (name[0].isalpha() or name[0] == "_") or not name.replace("_", "a").isalnum():
            fail("defines must be NAME or NAME=VALUE with a C identifier as NAME, not {}".format(define))

def _devicetree_impl(ctx):
    _validate_defines(ctx.attr.defines)
    debian_tools = ctx.toolchains[DEBIAN_TOOLS_TOOLCHAIN_TYPE].debian_tools
    output = ctx.actions.declare_file(ctx.label.name + ".dtb")
    arguments = ctx.actions.args()
    arguments.add(ctx.file._script)
    arguments.add("--launcher", debian_tools.launcher.executable)
    arguments.add("--src", ctx.file.src)
    arguments.add_all(ctx.files.hdrs, before_each = "--file")
    arguments.add_all(ctx.files.overlays, before_each = "--overlay")
    arguments.add_all(_include_directories(ctx), before_each = "--include-directory")
    arguments.add_all(ctx.attr.defines, before_each = "--define")
    arguments.add("--output", output)
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [ctx.file.src, ctx.file._script] + ctx.files.hdrs + ctx.files.overlays + ctx.files._script_modules,
        outputs = [output],
        mnemonic = "MkosiDevicetree",
        tools = [debian_tools.launcher],
        interpreter = static_python_interpreter(debian_tools.python, debian_tools.python_files_to_run),
        execution_requirements = mkosi_execution_requirements(True, offline = True),
        progress_message = "Building the device tree %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

devicetree = rule(
    implementation = _devicetree_impl,
    doc = """Builds a device tree blob, `<name>.dtb`, for `mkosi_image(devicetrees = ...)`.

It compiles `src` like the Linux kernel's build: `cpp -nostdinc -undef -x assembler-with-cpp -D__DTS__` with
`includes` and `defines`, so that sources can `#include` headers such as `<dt-bindings/gpio/gpio.h>` and use macros,
then `dtc`. `cpp`, `dtc` and `fdtoverlay` come from the pinned Debian tools and run without network; the output does
not depend on the build time, because `SOURCE_DATE_EPOCH` is 0 for `__DATE__` and `__TIME__`. With `overlays`, the base
is compiled with symbols (`dtc -@`) and `fdtoverlay` applies the overlays in order, failing if one does not apply.
The result must be a flattened device tree whose root node has a compatible string.

```starlark
devicetree(
    name = "board",
    src = "board.dts",
    hdrs = glob(["*.dtsi", "include/dt-bindings/**/*.h"]),
    includes = ["include"],
    overlays = ["display.dtso"],
    defines = ["BOARD_REVISION=2"],
)
```
""",
    attrs = {
        "defines": attr.string_list(
            doc = "Preprocessor definitions, `NAME` or `NAME=VALUE`, for `src` and the overlay sources.",
        ),
        "hdrs": attr.label_list(
            allow_files = [".dtsi", ".dts", ".dtso", ".h"],
            doc = "Files that `src` and the overlay sources include, with `#include` or dtc's `/include/`.",
        ),
        "includes": attr.string_list(
            doc = """Include directories, relative to this package, searched for `#include <...>` and `/include/`.

Each applies to the source and the generated files of the package. Quoted includes also search the including file's
directory.""",
        ),
        "overlays": attr.label_list(
            allow_files = [".dts", ".dtso", ".dtbo"],
            doc = """Overlays to apply in order: sources with `/plugin/;`, compiled like `src`, or compiled `.dtbo`
files. Overlays can refer to the base's labels, such as `&uart0`, and to paths, such as `&{/soc}`.""",
        ),
        "src": attr.label(
            allow_single_file = [".dts", ".dtb"],
            mandatory = True,
            doc = """The device tree source to compile, or a compiled `.dtb` to apply `overlays` to.""",
        ),
        "_script": attr.label(
            cfg = "exec",
            default = "//mkosi/private:devicetree_compile.py",
            allow_single_file = True,
        ),
        "_script_modules": attr.label_list(
            cfg = "exec",
            default = [
                "//mkosi/private:devicetree.py",
                "//mkosi/private:launcher_tool.py",
                "//mkosi/private:sibling_loader.py",
            ],
            allow_files = True,
        ),
    },
    toolchains = [DEBIAN_TOOLS_TOOLCHAIN_TYPE],
    exec_compatible_with = MKOSI_BUILD_EXEC_CONSTRAINTS,
)
