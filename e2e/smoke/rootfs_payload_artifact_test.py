"""Inspects typed payloads in the independent consumer's release rootfs."""

import os
import pathlib
import re
import sys

import rules_mkosi_disk_image as disk_image


def main() -> None:
    image_path, launcher = sys.argv[1:]
    filesystem = pathlib.Path(os.environ["TEST_TMPDIR"]) / "rootfs.ext4"
    disk_image.extract_root_partition(image_path, filesystem)

    expected_content = {
        "/usr/local/bin/example": "#!/bin/sh\necho consumer payload\n",
        "/usr/lib/systemd/system/example.service": (
            "[Unit]\nDescription=Consumer payload\n\n[Service]\nExecStart=/usr/local/bin/example\n"
        ),
        "/usr/lib/sysusers.d/example.conf": ('u example 61184 "Consumer payload user" /home/example\n'),
        "/usr/lib/tmpfiles.d/example.conf": (
            "d /home/example 0755 example example -\nL+ /opt/generated/config-link - - - - config\n"
        ),
        "/etc/skel/.config/example/config": "declarative skel home configuration\n",
        "/opt/generated/config": "generated TreeArtifact configuration\n",
    }
    for path, expected in expected_content.items():
        content = disk_image.read_file(launcher, filesystem, path).decode()
        if expected not in content:
            raise AssertionError("{} has unexpected content: {!r}".format(path, content))
        stat = disk_image.run_debugfs(launcher, filesystem, "stat " + path)
        if not re.search(r"User:\s+0\b", stat) or not re.search(r"Group:\s+0\b", stat):
            raise AssertionError("{} is not root-owned: {}".format(path, stat))

    executable = disk_image.run_debugfs(launcher, filesystem, "stat /usr/local/bin/example")
    if not re.search(r"Mode:\s+0755\b", executable):
        raise AssertionError("binary is not executable: {}".format(executable))
    link = disk_image.run_debugfs(launcher, filesystem, "stat /opt/generated/config-link")
    if 'Fast link dest: "config"' not in link:
        raise AssertionError("relative payload symlink is invalid: {}".format(link))


if __name__ == "__main__":
    main()
