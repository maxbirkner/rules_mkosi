"""Materialize an offline systemd-sysupdate payload with a digest manifest."""

import argparse
import hashlib
import pathlib
import shutil


def _copy(source, destination):
    digest = hashlib.sha256()
    with open(source, "rb") as src, open(destination, "wb") as dst:
        while chunk := src.read(1024 * 1024):
            digest.update(chunk)
            dst.write(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--verity", required=True)
    parser.add_argument("--uki", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = pathlib.Path(args.output)
    source = output / "source"
    definitions = output / "definitions"
    source.mkdir(parents=True)
    definitions.mkdir(parents=True)

    names = {
        "root": "root-{}.raw".format(args.version),
        "verity": "verity-{}.raw".format(args.version),
        "uki": "rules-mkosi_{}.efi".format(args.version),
    }
    digests = {}
    for role, path in (("root", args.root), ("verity", args.verity), ("uki", args.uki)):
        digests[names[role]] = _copy(path, source / names[role])
    (source / "SHA256SUMS").write_text(
        "".join("{}  {}\n".format(digests[name], name) for name in sorted(digests)),
        encoding="ascii",
    )

    common = """[Source]
Type=regular-file
Path=.
PathRelativeTo=explicit
MatchPattern={source}

[Target]
{target}"""
    (definitions / "10-root.transfer").write_text(
        common.format(
            source="root-@v.raw",
            target="""Type=partition
Path=auto
MatchPattern=root-@v
MatchPartitionType=root-x86-64
PartitionNoAuto=no
ReadOnly=yes""",
        ),
        encoding="ascii",
    )
    (definitions / "20-verity.transfer").write_text(
        common.format(
            source="verity-@v.raw",
            target="""Type=partition
Path=auto
MatchPattern=verity-@v
MatchPartitionType=root-x86-64-verity
PartitionNoAuto=no
ReadOnly=yes""",
        ),
        encoding="ascii",
    )
    (definitions / "90-uki.transfer").write_text(
        common.format(
            source="rules-mkosi_@v.efi",
            target="""Type=regular-file
Path=EFI/Linux
PathRelativeTo=boot
MatchPattern=rules-mkosi_@v+3-0.efi
Mode=0444
TriesLeft=3
TriesDone=0""",
        ),
        encoding="ascii",
    )
    script = output / "apply-update"
    script.write_text(
        """#!/bin/sh
set -eu
echo RULES_MKOSI_SLOT_A_VERSION=1
/usr/bin/systemd-repart --dry-run=no --definitions=/usr/lib/rules-mkosi-repart.d /dev/vda
cd /opt/rules-mkosi/source
sha256sum -c SHA256SUMS
echo RULES_MKOSI_UPDATE_DIGESTS_VERIFIED
/usr/lib/systemd/systemd-sysupdate --definitions=/opt/rules-mkosi/definitions --transfer-source=/opt/rules-mkosi/source --verify=yes update {version}
echo RULES_MKOSI_SYSUPDATE_APPLIED_VERSION={version}
touch /efi/rules-mkosi-update-applied
sync
systemctl poweroff
""".format(version=args.version),
        encoding="ascii",
    )
    script.chmod(0o755)
if __name__ == "__main__":
    main()
