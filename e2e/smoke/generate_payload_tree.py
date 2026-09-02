"""Generates a deterministic TreeArtifact rootfs payload."""

import os
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
generated = root / "generated.txt"
root.mkdir(parents=True)
generated.write_text("generated TreeArtifact payload\n")
os.chmod(generated, 0o644)
os.utime(generated, (0, 0))
for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
    os.chmod(path, 0o755)
    os.utime(path, (0, 0))
os.chmod(root, 0o755)
os.utime(root, (0, 0))
