"""Regression tests for the wrapper's input-root and metadata handling."""

import importlib.util
import os
import pathlib
import stat
import sys


def _load_wrapper(path):
    spec = importlib.util.spec_from_file_location("run_mkosi", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare(root, name, mode, timestamp):
    source = root / name
    (source / "linked-dir").mkdir(parents=True)
    (source / "file-target").write_text("file\n")
    (source / "linked-dir" / "marker").write_text("directory\n")
    (source / "linked-file").symlink_to("file-target")
    (source / "linked-directory").symlink_to("linked-dir")
    os.chmod(source / "file-target", mode)
    os.chmod(source / "linked-dir" / "marker", mode)
    os.utime(source / "file-target", (timestamp, timestamp))
    os.utime(source / "linked-dir" / "marker", (timestamp, timestamp))
    os.symlink(source, root / "{}-root-link".format(name))
    return source


def _assert_normalized(path):
    assert stat.S_IMODE(path.stat().st_mode) == 0o755
    assert path.stat().st_mtime == 0
    assert stat.S_IMODE((path / "file-target").stat().st_mode) == 0o644
    assert (path / "file-target").stat().st_mtime == 0
    assert stat.S_IMODE((path / "linked-dir").stat().st_mode) == 0o755
    assert (path / "linked-dir").stat().st_mtime == 0
    assert (path / "linked-file").is_symlink()
    assert os.readlink(path / "linked-file") == "file-target"
    assert (path / "linked-directory").is_symlink()
    assert os.readlink(path / "linked-directory") == "linked-dir"


def main():
    wrapper = _load_wrapper(sys.argv[1])
    root = pathlib.Path(os.environ["TEST_TMPDIR"])
    first = _prepare(root, "first", 0o600, 946684800)
    second = _prepare(root, "second", 0o644, 1893456000)
    wrapper._materialize_tree(root / "first-root-link", root / "out-first")
    wrapper._materialize_tree(root / "second-root-link", root / "out-second")
    _assert_normalized(root / "out-first")
    _assert_normalized(root / "out-second")
    assert (root / "out-first/file-target").read_bytes() == (root / "out-second/file-target").read_bytes()
    assert first != second
    print("materialized metadata and relative links are deterministic")


if __name__ == "__main__":
    main()
