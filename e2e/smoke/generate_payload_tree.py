"""Generates a deterministic TreeArtifact rootfs payload."""

import os
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
config = root / "config"
config.write_text("generated TreeArtifact configuration\n")
link = root / "config-link"
link.symlink_to("config")
os.chmod(config, 0o644)
os.utime(config, (0, 0))
os.utime(link, (0, 0), follow_symlinks=False)
for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
    os.chmod(path, 0o755)
    os.utime(path, (0, 0))
os.chmod(root, 0o755)
os.utime(root, (0, 0))
