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
    if [ -e "$runfiles_root/$path" ]; then
        printf '%s/%s' "$runfiles_root" "$path"
    elif [ -e "$runfiles_root/_main/$path" ]; then
        printf '%s/_main/%s' "$runfiles_root" "$path"
    elif [ -e "$runfiles_root/rules_mkosi/$path" ]; then
        printf '%s/rules_mkosi/%s' "$runfiles_root" "$path"
    else
        found="$(/usr/bin/find "$runfiles_root" -path "*/$path" -print -quit)"
        if [ -n "$found" ]; then
            printf '%s' "$found"
        else
            printf '%s/%s' "$runfiles_root" "$path"
        fi
    fi
}}
qemu="$(runfile {qemu})"
qemu_img="$(runfile {qemu_img})"
system_data="$(runfile {system_data})"
ovmf_code="$(runfile {ovmf_code})"
ovmf_vars="$(runfile {ovmf_vars})"
ovmf_shell="$(runfile {ovmf_shell})"
firmware_validator="$(runfile {firmware_validator})"

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
if ! "$qemu_img" --version >/dev/null 2>&1; then
    echo "qemu-img failed to start: $qemu_img" >&2
    exit 1
fi

vars_copy="$TEST_TMPDIR/OVMF_VARS.fd"
/bin/cp "$ovmf_vars" "$vars_copy"
"$firmware_validator" "$ovmf_code" "$ovmf_vars" "$ovmf_shell" \
    {ovmf_code_sha256} {ovmf_vars_sha256} {ovmf_shell_sha256} "$vars_copy"
esp_dir="$TEST_TMPDIR/uefi-esp"
/bin/mkdir -p "$esp_dir/EFI/BOOT"
/bin/cp "$ovmf_shell" "$esp_dir/EFI/BOOT/BOOTX64.EFI"
serial_log="$TEST_TMPDIR/uefi-serial.log"
qemu_log="$TEST_TMPDIR/qemu.log"
qmp_fifo="$TEST_TMPDIR/qmp.fifo"
/usr/bin/mkfifo "$qmp_fifo"
exec 3<> "$qmp_fifo"
TMPDIR="$TEST_TMPDIR"
export TMPDIR
"$qemu" -L "$system_data" -machine q35 -accel tcg -m 128M \
    -nodefaults -nographic -serial "file:$serial_log" -qmp stdio \
    -drive "if=pflash,format=raw,readonly=on,file=$ovmf_code" \
    -drive "if=pflash,format=raw,file=$vars_copy" \
    -drive "file=fat:rw:$esp_dir,format=raw" >"$TEST_TMPDIR/qmp.log" 2>"$qemu_log" <&3 &
qemu_pid=$!
ready=0
iteration=0
while [ "$iteration" -lt 100 ]
do
    if [ -f "$serial_log" ] && /usr/bin/grep -Fq "Shell>" "$serial_log"; then
        ready=1
        break
    fi
    if ! kill -0 "$qemu_pid" 2>/dev/null; then
        break
    fi
    /bin/sleep 0.1
    iteration=$((iteration + 1))
done
if [ "$ready" -ne 1 ]; then
    echo "timed out waiting for UEFI shell readiness from QEMU=$qemu OVMF_CODE=$ovmf_code OVMF_VARS=$vars_copy UEFI_SHELL=$ovmf_shell" >&2
    /bin/cat "$serial_log" "$qemu_log" >&2 2>/dev/null || true
    kill "$qemu_pid" 2>/dev/null || true
    wait "$qemu_pid" 2>/dev/null || true
    exit 1
fi

printf '{{"execute":"qmp_capabilities"}}\\r\\n{{"execute":"quit"}}\\r\\n' >&3
iteration=0
while kill -0 "$qemu_pid" 2>/dev/null && [ "$iteration" -lt 50 ]
do
    /bin/sleep 0.1
    iteration=$((iteration + 1))
done
if kill -0 "$qemu_pid" 2>/dev/null; then
    echo "QEMU did not terminate after UEFI readiness: $qemu (OVMF_CODE=$ovmf_code, OVMF_VARS=$vars_copy)" >&2
    kill "$qemu_pid" 2>/dev/null || true
    wait "$qemu_pid" 2>/dev/null || true
    exit 1
fi
wait "$qemu_pid" || {{
    echo "QEMU failed after UEFI readiness: $qemu (OVMF_CODE=$ovmf_code, OVMF_VARS=$vars_copy, UEFI_SHELL=$ovmf_shell)" >&2
    /bin/cat "$qemu_log" >&2 2>/dev/null || true
    exit 1
}}
exec 3>&-
""".format(
            qemu = repr(toolchain.qemu_files_to_run.executable.short_path),
            qemu_img = repr(toolchain.qemu_img.short_path),
            system_data = repr(toolchain.system_data_anchor.short_path),
            ovmf_code = repr(toolchain.ovmf_code.short_path),
            ovmf_vars = repr(toolchain.ovmf_vars.short_path),
            ovmf_shell = repr(toolchain.ovmf_shell.short_path),
            firmware_validator = repr("mkosi/private/qemu_ovmf_validate.sh"),
            ovmf_code_sha256 = repr(toolchain.ovmf_code_sha256),
            ovmf_vars_sha256 = repr(toolchain.ovmf_vars_sha256),
            ovmf_shell_sha256 = repr(toolchain.ovmf_shell_sha256),
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
                    toolchain.ovmf_shell,
                    ctx.file._firmware_validator,
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
    test = True,
    toolchains = [_QEMU_TOOLCHAIN_TYPE],
    attrs = {
        "_firmware_validator": attr.label(
            allow_single_file = True,
            default = "//mkosi/private:qemu_ovmf_validate.sh",
        ),
    },
    doc = "Starts a minimal QEMU/OVMF process and terminates through QMP.",
)
