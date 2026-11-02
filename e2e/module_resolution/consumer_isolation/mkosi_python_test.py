import subprocess
import sys

assert sys.version_info[:2] == (3, 14), sys.version
version = subprocess.run(
    [sys.argv[1], "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
    capture_output=True,
    check=True,
    text=True,
).stdout.strip()
assert version == "3.14", version
