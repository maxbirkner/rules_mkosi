"""Exercise Debian tools archive transport and action-local materialization."""

import hashlib
import importlib.util
import os
import pathlib
import sys


_EXPECTED_SHA256 = "ee26a2ba23d1fadb89b0fc6b2329a44206682ca243b89fe495246e827009729f"
sys.dont_write_bytecode = True


def main():
    archive = pathlib.Path(sys.argv[1])
    extractor_path = pathlib.Path(sys.argv[2])
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == _EXPECTED_SHA256

    spec = importlib.util.spec_from_file_location("extract_tree", extractor_path)
    assert spec is not None and spec.loader is not None
    extractor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extractor)

    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "debian-tools"
    extractor.extract(archive, root, _EXPECTED_SHA256)

    assert (root / "lib").is_symlink()
    assert os.readlink(root / "lib") == "usr/lib"
    assert (root / "lib/environment.d").is_dir()
    assert (root / "usr/lib/environment.d/99-environment.conf").is_symlink()
    print("archive transport preserved merged-/usr links in action-local materialization")


if __name__ == "__main__":
    main()
