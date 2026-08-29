"""Action-level QEMU and OVMF smoke test."""

_QEMU_TOOLCHAIN_TYPE = "//mkosi/toolchain:qemu_toolchain_type"

def _qemu_ovmf_smoke_test_impl(ctx):
    toolchain = ctx.toolchains[_QEMU_TOOLCHAIN_TYPE].qemu
    executable = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(
        output = executable,
        is_executable = True,
        content = """#!/bin/sh
set -eu
PATH=
export PATH
runfiles_root="${{RUNFILES_DIR:-$0.runfiles}}"
runfile() {{
    path="$1"
    path="${{path#../}}"
    path="${{path#external/}}"
    printf '%s/%s' "$runfiles_root" "$path"
}}
qemu="$(runfile {qemu})"
qemu_img="$(runfile {qemu_img})"
system_data="$(runfile {system_data})"
ovmf_code="$(runfile {ovmf_code})"
ovmf_vars="$(runfile {ovmf_vars})"

if [ ! -x "$qemu" ]; then
    echo "QEMU executable is missing or not executable: $qemu" >&2
    exit 1
fi
if [ ! -x "$qemu_img" ]; then
    echo "qemu-img executable is missing or not executable: $qemu_img" >&2
    exit 1
fi
if [ ! -d "$system_data" ]; then
    echo "QEMU system data artifact is missing: $system_data" >&2
    exit 1
fi
if [ ! -f "$ovmf_code" ]; then
    echo "OVMF_CODE firmware artifact is missing: $ovmf_code" >&2
    exit 1
fi
if [ ! -f "$ovmf_vars" ]; then
    echo "OVMF_VARS firmware artifact is missing: $ovmf_vars" >&2
    exit 1
fi
if ! "$qemu_img" --version >/dev/null 2>&1; then
    echo "qemu-img failed to start: $qemu_img" >&2
    exit 1
fi

printf '{{"execute":"qmp_capabilities"}}\\r\\n{{"execute":"quit"}}\\r\\n' |
    "$qemu" -L "$system_data" -machine q35 -accel tcg \
    -nodefaults -display none -serial none -S -qmp stdio \
    -drive "if=pflash,format=raw,readonly=on,file=$ovmf_code" \
    -drive "if=pflash,format=raw,readonly=on,file=$ovmf_vars" ||
    {{
        echo "QEMU failed to start with OVMF firmware: $ovmf_code, $ovmf_vars" >&2
        exit 1
    }}
""".format(
            qemu = repr(toolchain.qemu_files_to_run.executable.short_path),
            qemu_img = repr(toolchain.qemu_img.short_path),
            system_data = repr(toolchain.system_data_anchor.short_path),
            ovmf_code = repr(toolchain.ovmf_code.short_path),
            ovmf_vars = repr(toolchain.ovmf_vars.short_path),
        ),
    )
    return [
        DefaultInfo(
            executable = executable,
            runfiles = ctx.runfiles(
                files = [
                    executable,
                    toolchain.qemu_files_to_run.executable,
                    toolchain.qemu_img,
                    toolchain.system_data_anchor,
                    toolchain.ovmf_code,
                    toolchain.ovmf_vars,
                ],
                transitive_files = depset(transitive = [
                    toolchain.system_data_files,
                    toolchain.qemu_runfiles.files,
                ]),
            ),
        ),
    ]

qemu_ovmf_smoke_test = rule(
    implementation = _qemu_ovmf_smoke_test_impl,
    attrs = {},
    test = True,
    toolchains = [_QEMU_TOOLCHAIN_TYPE],
    doc = "Starts a minimal QEMU/OVMF process and terminates through QMP.",
)
