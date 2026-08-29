"""Pinned mkosi releases supported by rules_mkosi."""

DEFAULT_MKOSI_VERSION = "27"

MKOSI_VERSIONS = {
    "27": struct(
        source_url = "https://github.com/systemd/mkosi/archive/4736cd836108a97772142c461c49f1ddb4172348.tar.gz",
        source_sha256 = "fa34b3ba66cc71d202b267a0f55e6c77f41d8db273ea5404f7fad99e464835f8",
        source_integrity = "sha256-+jSzumbMcdICsmeg9V5sd/QdjbJz6lQE9/rZnkZINfg=",
        strip_prefix = "mkosi-4736cd836108a97772142c461c49f1ddb4172348",
        python_version = "3.11",
        python_dependencies = ["@mkosi_pypi//pefile"],
        python_import_dependencies = ["@mkosi_pypi//pefile"],
    ),
}
