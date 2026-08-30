#!/bin/sh
set -eu

# This test intentionally uses only POSIX shell builtins outside the
# advertised launcher.  All commands inspected below are from the packaged
# Debian root, never from the host PATH.
PATH=
export PATH
runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
launcher=
mapping="$runfiles_root/_repo_mapping"
if [ -f "$mapping" ]; then
    while IFS= read -r mapping_line
    do
        case "$mapping_line" in
            ",mkosi_debian_tools,"*)
                repository="${mapping_line#*,mkosi_debian_tools,}"
                launcher="$runfiles_root/$repository/launcher"
                break
                ;;
        esac
    done < "$mapping"
fi
[ -x "$launcher" ] || {
    echo "advertised Debian launcher is missing" >&2
    exit 1
}

hostile_sitecustomize="$TEST_TMPDIR/sitecustomize.py"
printf '%s\n' 'raise RuntimeError("hostile sitecustomize loaded")' > "$hostile_sitecustomize"
set +e
hostile_output="$(
    PYTHONPATH="$TEST_TMPDIR" \
    PYTHONHOME="$TEST_TMPDIR" \
    PYTHONSTARTUP="$hostile_sitecustomize" \
    PYTHONINSPECT=1 \
    LD_PRELOAD="$hostile_sitecustomize" \
    LD_LIBRARY_PATH="$TEST_TMPDIR" \
    MKOSI_DEBIAN_TOOLS_SCRATCH="$TEST_TMPDIR/debian-tools-hostile" \
    "$launcher" /usr/bin/dpkg --version 2>&1
)"
hostile_status=$?
set -e
[ "$hostile_status" -eq 0 ] || {
    echo "hostile Python/loader environment changed launcher status: $hostile_status" >&2
    echo "$hostile_output" >&2
    exit 1
}
case "$hostile_output" in
    *"hostile sitecustomize loaded"*)
        echo "hostile sitecustomize was imported" >&2
        exit 1
        ;;
esac

run_tool() {
    name="$1"
    expected="$2"
    shift 2
    scratch="$TEST_TMPDIR/debian-tools-$name"
    set +e
    output="$(MKOSI_DEBIAN_TOOLS_SCRATCH="$scratch" "$launcher" "$@" 2>&1)"
    status=$?
    set -e
    [ "$status" -eq 0 ] || {
        echo "$name returned $status, expected 0" >&2
        echo "$output" >&2
        exit 1
    }
    case "$output" in
        *"$expected"*) ;;
        *)
            echo "$name did not produce its recognizable output: $expected" >&2
            echo "$output" >&2
            exit 1
            ;;
    esac
}

run_tool apt-get "apt" /usr/bin/apt-get --version
run_tool dpkg "Debian" /usr/bin/dpkg --version
run_tool systemd-repart "systemd " /usr/bin/systemd-repart --version
run_tool mkfs-ext4 "EXT2FS" /usr/sbin/mkfs.ext4 -V
run_tool mkfs-fat "mkfs.fat" /usr/sbin/mkfs.fat --help
run_tool mkfs-btrfs "btrfs-progs" /usr/sbin/mkfs.btrfs --version
run_tool sfdisk "sfdisk" /usr/sbin/sfdisk --version
run_tool parted "parted" /usr/sbin/parted --version
run_tool grub-install "grub-install" /usr/sbin/grub-install --version
run_tool bootctl "systemd" /usr/bin/bootctl --version
run_tool objcopy "GNU objcopy" /usr/bin/objcopy --version

runtime_scratch="$TEST_TMPDIR/debian-tools-runtime"
host_marker="$TEST_TMPDIR/debian-tools-host-only"
printf '%s\n' host-only > "$host_marker"
set +e
runtime_output="$(
    MKOSI_DEBIAN_TOOLS_SCRATCH="$runtime_scratch" "$launcher" /bin/sh -c '
        [ "$PWD" = /workspace ]
        [ "$HOME" = /root ]
        [ -d /tmp ] && [ -d /proc ] && [ -c /dev/null ]
        IFS= read -r namespace_hostname < /proc/sys/kernel/hostname
        IFS= read -r namespace_domain < /proc/sys/kernel/domainname
        [ "$namespace_hostname" = mkosi-debian-tools ]
        [ "$namespace_domain" = localdomain ]
        namespace_groups=
        while IFS= read -r status_line
        do
            case "$status_line" in
                Groups:*) namespace_groups="$status_line" ;;
            esac
        done < /proc/self/status
        zero_groups=0
        for group in $namespace_groups
        do
            case "$group" in
                Groups:) ;;
                0) zero_groups=$((zero_groups + 1)) ;;
                65534) ;;
                *) exit 1 ;;
            esac
        done
        [ "$zero_groups" -eq 1 ]
        printf "groups=%s\n" "$namespace_groups"
        tmpfs=0
        procfs=0
        devfs=0
        while IFS= read -r mount_line
        do
            case "$mount_line" in
                *" /tmp "*"- tmpfs "*) tmpfs=1 ;;
                *" /proc "*"- proc "*) procfs=1 ;;
                *" /dev "*"- tmpfs "*) devfs=1 ;;
            esac
        done < /proc/self/mountinfo
        [ "$tmpfs" -eq 1 ] && [ "$procfs" -eq 1 ] && [ "$devfs" -eq 1 ]
        [ ! -e "$1" ]
        printf "tmp\n" > /tmp/runtime-probe
        printf "home\n" > "$HOME/runtime-probe"
        printf "workspace\n" > /workspace/runtime-probe
        printf "runtime=%s,%s,%s,%s\n" "$PWD" "$HOME" "$tmpfs" "$procfs"
    ' sh "$host_marker" 2>&1
)"
runtime_status=$?
set -e
printf '%s\n' "$runtime_output"
[ "$runtime_status" -eq 0 ] || {
    echo "runtime namespace contract failed with status $runtime_status" >&2
    echo "$runtime_output" >&2
    exit 1
}
case "$runtime_output" in
    *"runtime=/workspace,/root,1,1"*) ;;
    *)
        echo "runtime namespace output was not exact" >&2
        echo "$runtime_output" >&2
        exit 1
        ;;
esac

input="$TEST_TMPDIR/debian-tools-input"
output="$TEST_TMPDIR/debian-tools-output"
counter="$TEST_TMPDIR/debian-tools-counter"
printf '%s\n' "packaged-input" > "$input"
: > "$output"
: > "$counter"
set +e
bind_output="$(
    MKOSI_DEBIAN_TOOLS_SCRATCH="$TEST_TMPDIR/debian-tools-binds" "$launcher" \
        --ro-bind "$input:/inputs/input.txt" \
        --ro-bind "$TEST_TMPDIR:/inputs/input-dir" \
        --rw-bind "$output:/outputs/output.txt" \
        /bin/sh -c '
            IFS= read -r value < /inputs/input.txt
            [ "$value" = packaged-input ]
            [ -d /inputs/input-dir ]
            printf "packaged-output\n" > /outputs/output.txt
        ' 2>&1
)"
bind_status=$?
set -e
[ "$bind_status" -eq 0 ] || {
    echo "typed input/output bind failed with status $bind_status" >&2
    echo "$bind_output" >&2
    exit 1
}
IFS= read -r value < "$output"
[ "$value" = packaged-output ]

set +e
once_output="$(
    MKOSI_DEBIAN_TOOLS_SCRATCH="$TEST_TMPDIR/debian-tools-once" "$launcher" \
        --rw-bind "$counter:/outputs/counter" \
        /bin/sh -c 'printf "x\n" >> /outputs/counter; exit 37' 2>&1
)"
once_status=$?
set -e
[ "$once_status" -eq 37 ] || {
    echo "distinctive nonzero status was not propagated exactly: $once_status" >&2
    echo "$once_output" >&2
    exit 1
}
assert_one_x_record() {
    exec 3< "$1"
    first=
    second=
    first_status=0
    IFS= read -r first <&3 || first_status=$?
    second_status=0
    IFS= read -r second <&3 || second_status=$?
    exec 3<&-
    [ "$first_status" -eq 0 ] && [ "$first" = x ] &&
        [ "$second_status" -ne 0 ] && [ -z "$second" ]
}
assert_one_x_record "$counter" || {
    echo "launcher did not execute the nonzero command exactly once" >&2
    exit 1
}
duplicate="$TEST_TMPDIR/debian-tools-duplicate-counter"
printf 'x\nx\n' > "$duplicate"
if assert_one_x_record "$duplicate"; then
    echo "duplicate execution records were accepted" >&2
    exit 1
fi

set +e
(
    trap '' CHLD
    MKOSI_DEBIAN_TOOLS_SCRATCH="$TEST_TMPDIR/debian-tools-sigchld" \
        "$launcher" /bin/sh -c 'exit 37'
)
ignored_chld_status=$?
set -e
[ "$ignored_chld_status" -eq 37 ] || {
    echo "SIGCHLD=SIG_IGN did not preserve synchronous status: $ignored_chld_status" >&2
    exit 1
}

run_tool openssl "OK" /usr/bin/openssl verify \
    -CAfile /etc/ssl/certs/ca-certificates.crt \
    /usr/share/ca-certificates/mozilla/ACCVRAIZ1.crt
