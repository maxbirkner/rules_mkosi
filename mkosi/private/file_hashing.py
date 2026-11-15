"""SHA-256 digests of files read by rules_mkosi actions."""

import hashlib
import os


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Returns the lowercase hex SHA-256 of the file at path; raises OSError if it cannot be read."""
    with open(path, "rb") as source:
        # Actions run this on the Debian tools' Python, which has file_digest; mypy checks for the Python 3.10 of the
        # host scripts.
        digest = hashlib.file_digest(source, "sha256")  # type: ignore[attr-defined]
    return digest.hexdigest()
