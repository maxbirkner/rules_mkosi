"""Prepares the sandbox files of a build that downloads packages from the network."""

import os

from . import tree

# Makes apt retry transient download failures, such as a throttling mirror, with its exponential back-off.
APT_CONFIGURATION = 'Acquire::Retries "10";\n'


def configure_network_sandbox(workspace, arguments):
    """Adds a sandbox tree whose apt configuration retries failed downloads."""
    sandbox_tree = workspace / "network-sandbox"
    tree.write_file(sandbox_tree / "etc/apt/apt.conf.d/99rules-mkosi-retries", APT_CONFIGURATION)
    arguments.extend(["--sandbox-tree", os.fspath(sandbox_tree)])
