"""Native test launcher for a Bazel-managed Python interpreter."""

def _managed_python_test_impl(ctx):
    runtime = ctx.toolchains["@rules_python//python:toolchain_type"].py3_runtime
    if runtime.interpreter == None:
        fail("managed_python_test requires an in-build Python interpreter")

    executable = ctx.actions.declare_file(ctx.label.name)
    interpreter_short_path = runtime.interpreter.short_path
    if interpreter_short_path.startswith("../"):
        interpreter_short_path = interpreter_short_path[3:]
    source_short_path = ctx.file.src.short_path
    if source_short_path.startswith("../"):
        source_short_path = source_short_path[3:]
    ctx.actions.write(
        output = executable,
        is_executable = True,
        content = """#!/bin/sh
set -eu
        export PYTHONNOUSERSITE=1

        runfile() {
    logical="$1"
    runfiles_dir="${RUNFILES_DIR:-}"
    if [ -n "$runfiles_dir" ]; then
        for candidate in "$logical" "_main/$logical"; do
            if [ -e "$runfiles_dir/$candidate" ]; then
                printf '%%s\\n' "$runfiles_dir/$candidate"
                return
            fi
        done
        case "$logical" in
            external/*)
                logical="${logical#external/}"
                if [ -e "$runfiles_dir/$logical" ]; then
                    printf '%%s\\n' "$runfiles_dir/$logical"
                    return
                fi
                ;;
        esac
    fi
    manifest="${RUNFILES_MANIFEST_FILE:-}"
    if [ -n "$manifest" ] && [ -f "$manifest" ]; then
        for candidate in "$logical" "_main/$logical"; do
            while IFS= read -r line; do
                case "$line" in
                    "$candidate "*) printf '%%s\\n' "${line#"$candidate "}" ; return ;;
                esac
            done < "$manifest"
        done
        case "$logical" in
            external/*)
                logical="${logical#external/}"
                while IFS= read -r line; do
                    case "$line" in
                        "$logical "*) printf '%%s\\n' "${line#"$logical "}" ; return ;;
                    esac
                done < "$manifest"
                ;;
        esac
    fi
    echo "managed_python_test runfile is missing: $1" >&2
    exit 1
}

exec "$(runfile "%s")" "$(runfile "%s")" "$@"
""" % (interpreter_short_path, source_short_path),
    )

    transitive_files = [runtime.files or depset()]
    for data in ctx.attr.data:
        transitive_files.append(data[DefaultInfo].files)
    runfiles = ctx.runfiles(
        files = [ctx.file.src],
        transitive_files = depset(transitive = transitive_files),
    )
    for data in ctx.attr.data:
        runfiles = runfiles.merge(data[DefaultInfo].default_runfiles)

    return [
        DefaultInfo(
            executable = executable,
            runfiles = runfiles,
        ),
        RunEnvironmentInfo(environment = {"PYTHONNOUSERSITE": "1"}),
    ]

_managed_python_attrs = {
    "src": attr.label(
        allow_single_file = [".py"],
        mandatory = True,
        doc = "Python script automatically passed as the interpreter's first argument.",
    ),
    "data": attr.label_list(allow_files = True),
}

managed_python_binary = rule(
    implementation = _managed_python_test_impl,
    executable = True,
    attrs = _managed_python_attrs,
    toolchains = ["@rules_python//python:toolchain_type"],
    doc = "Runs src with the registered managed interpreter, followed by arguments.",
)

managed_python_test = rule(
    implementation = _managed_python_test_impl,
    test = True,
    attrs = _managed_python_attrs,
    toolchains = ["@rules_python//python:toolchain_type"],
    doc = "Tests src with the registered managed interpreter, followed by args.",
)
