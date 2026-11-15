"""Inspects typed payloads in the independent consumer's release rootfs."""

import json
import os
import pathlib
import re
import sys

from rootfs_debugfs import run_debugfs


def main() -> None:
    image_path, metadata_path, launcher = sys.argv[1:]
    metadata = json.loads(pathlib.Path(metadata_path).read_text())
    roots = [partition for partition in metadata["partitions"] if partition["label"] == "root-x86-64"]
    if len(roots) != 1:
        raise AssertionError("expected one root-x86-64 partition")
    root = roots[0]
    directory = pathlib.Path(os.environ["TEST_TMPDIR"])
    filesystem = directory / "rootfs.ext4"
    with open(image_path, "rb") as image, filesystem.open("wb") as output:
        image.seek(root["start_bytes"])
        remaining = root["size_bytes"]
        while remaining:
            chunk = image.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise AssertionError("root partition is truncated")
            output.write(chunk)
            remaining -= len(chunk)

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
        content = run_debugfs(launcher, directory, "payload-test", "cat {}".format(path))
        if expected not in content:
            raise AssertionError("{} has unexpected content: {!r}".format(path, content))
        stat = run_debugfs(launcher, directory, "payload-test", "stat {}".format(path))
        if not re.search(r"User:\s+0\b", stat) or not re.search(r"Group:\s+0\b", stat):
            raise AssertionError("{} is not root-owned: {}".format(path, stat))

    executable = run_debugfs(launcher, directory, "payload-test", "stat /usr/local/bin/example")
    if not re.search(r"Mode:\s+0755\b", executable):
        raise AssertionError("binary is not executable: {}".format(executable))
    link = run_debugfs(launcher, directory, "payload-test", "stat /opt/generated/config-link")
    if 'Fast link dest: "config"' not in link:
        raise AssertionError("relative payload symlink is invalid: {}".format(link))


if __name__ == "__main__":
    main()
