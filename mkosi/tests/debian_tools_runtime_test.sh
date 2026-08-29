#!/bin/sh
set -eu
PATH=
export PATH
runfiles_root="${RUNFILES_DIR:-$0.runfiles}"
python_bin=
script=
archive=
extractor=
if [ -n "${RUNFILES_MANIFEST_FILE:-}" ]; then
    while IFS= read -r manifest_line
    do
        case "$manifest_line" in
            *"/bin/python3 "*)
                python_bin="${manifest_line#* }"
                break
                ;;
        esac
    done < "$RUNFILES_MANIFEST_FILE"
fi
if [ -z "$python_bin" ]; then
    for candidate in "$runfiles_root"/*/bin/python3 "$runfiles_root"/*/*/bin/python3 "$runfiles_root"/*/*/*/bin/python3
    do
        if [ -x "$candidate" ]; then python_bin="$candidate"; break; fi
    done
fi
if [ -z "$script" ]; then
    for candidate in "$runfiles_root"/*/debian_launcher.py "$runfiles_root"/*/*/debian_launcher.py "$runfiles_root"/*/*/*/debian_launcher.py
    do
        if [ -f "$candidate" ]; then script="$candidate"; break; fi
    done
fi
if [ -z "$archive" ]; then
    for candidate in "$runfiles_root"/*/flat.tar "$runfiles_root"/*/*/flat.tar "$runfiles_root"/*/*/*/flat.tar
    do
        if [ -f "$candidate" ]; then archive="$candidate"; break; fi
    done
fi
if [ -z "$extractor" ]; then
    for candidate in "$runfiles_root"/*/extract_tree.py "$runfiles_root"/*/*/extract_tree.py "$runfiles_root"/*/*/*/extract_tree.py
    do
        if [ -f "$candidate" ]; then extractor="$candidate"; break; fi
    done
fi
if [ -z "${python_bin:-}" ]; then
    for candidate in \
        "$runfiles_root"/*/bin/python3 \
        "$runfiles_root"/*/*/bin/python3 \
        "$runfiles_root"/*/*/*/bin/python3
    do
        if [ -x "$candidate" ]; then
            python_bin="$candidate"
            break
        fi
    done
fi
if [ -n "${RUNFILES_MANIFEST_FILE:-}" ]; then
    while IFS= read -r manifest_line
    do
        case "$manifest_line" in
            *"debian_launcher.py "*)
                script="${manifest_line#* }"
                ;;
            *"extract_tree.py "*)
                extractor="${manifest_line#* }"
                ;;
            *"/flat.tar "*)
                archive="${manifest_line#* }"
                ;;
        esac
    done < "$RUNFILES_MANIFEST_FILE"
fi
[ -x "${python_bin:-}" ] || {
    echo "Bazel-managed Python interpreter is missing from runfiles" >&2
    exit 1
}
[ -f "$script" ] || {
    echo "Debian launcher script is missing from runfiles" >&2
    exit 1
}
export DEBIAN_TOOLS_ARCHIVE="$archive"
export DEBIAN_TOOLS_EXTRACTOR="$extractor"
export DEBIAN_TOOLS_ARCHIVE_SHA256="f1c9a83ec17380d5a35ff37e263d09f27c1ddd7ab57f34be48a7b0d329bf5975"
run_launcher() {
    run=$((run + 1))
    scratch="$TEST_TMPDIR/debian-tools-scratch-$run-$$"
    /bin/mkdir "$scratch"
    MKOSI_DEBIAN_TOOLS_SCRATCH="$scratch" "$python_bin" "$script" "$@"
}
run=0

run_launcher /bin/sh -c \
    'test -L /bin && test -L /sbin && test -L /lib && test -L /lib64 && test -x /usr/bin/dpkg'
run_launcher /bin/sh -c \
    'test -s /etc/ssl/certs/ca-certificates.crt && test -e /usr/lib/ssl/cert.pem'

# The launcher supplies the extracted TreeArtifact as /, starts bubblewrap
# through the packaged ELF loader, and sets PATH only inside that namespace.
for tool in \
    /usr/bin/apt-get \
    /usr/bin/dpkg \
    /usr/bin/systemd-repart \
    /usr/sbin/mkfs.ext4 \
    /usr/sbin/mkfs.fat \
    /usr/sbin/mkfs.btrfs \
    /usr/sbin/sfdisk \
    /usr/sbin/parted \
    /usr/sbin/grub-install \
    /usr/bin/bootctl \
    /usr/bin/objcopy
do
    output="$TEST_TMPDIR/${tool##*/}.log"
    if run_launcher "$tool" --version >"$output" 2>&1
    then
        :
    else
        status=$?
        while IFS= read -r line
        do
            case "$line" in
                *"No such file"*|*"cannot open shared object file"*|*"not found"*)
                    echo "packaged root-isolated runtime failed for $tool: $line" >&2
                    exit 1
                    ;;
            esac
        done < "$output"
        [ "$status" -le 1 ] || {
            echo "packaged root-isolated tool failed: $tool (status=$status)" >&2
            exit 1
        }
    fi
done
