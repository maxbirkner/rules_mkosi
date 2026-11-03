"""Pinned mkosi releases supported by rules_mkosi."""

DEFAULT_MKOSI_VERSION = "27.1"
DEFAULT_PYTHON_VERSION = "3.14"

MKOSI_VERSIONS = {
    "27.1": struct(
        source_url = "https://github.com/systemd/mkosi/archive/ecf7f5702bb2052b7a69cab3fe7d37bc3b9ad77b.tar.gz",
        source_sha256 = "3d38e848f9b1108ec76d873f2c378dfc7d4b536ad89deffe8c97504f7a8dff43",
        source_integrity = "sha256-PTjoSPmxEI7HbYc/LDeN/H1LU2rYne/+jJdQT3qN/0M=",
        strip_prefix = "mkosi-ecf7f5702bb2052b7a69cab3fe7d37bc3b9ad77b",
        python_version = DEFAULT_PYTHON_VERSION,
        python_dependencies = ["@mkosi_pypi//pefile"],
        python_import_dependencies = ["@mkosi_pypi//pefile"],
    ),
}
