"""Loads rules_mkosi helper modules that Bazel stages next to the script that uses them.

Scripts run as Bazel actions, from test runfiles, and as modules imported by tests, so a sibling is loaded by path
rather than through sys.path. Scripts bootstrap this module with
``runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]``.
"""

import importlib.util
from pathlib import Path


def load_sibling(script, name):
    """Executes name.py from the directory of script as a fresh module named rules_mkosi_<name>.

    Raises RuntimeError if the file cannot be loaded as Python source.
    """
    path = Path(script).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("rules_mkosi_" + name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("rules_mkosi helper module cannot be loaded: {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
