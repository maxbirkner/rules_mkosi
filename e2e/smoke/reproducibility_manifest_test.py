"""Validate the public reproducibility projection."""

import json
import pathlib
import sys


manifest = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert manifest["format_version"] == "mkosi-reproducibility-manifest-v1"
assert all(
    excluded["field"] and excluded["reason"]
    for excluded in manifest["excluded_variable_fields"]
)
assert len(manifest["immutable_artifacts"]["build_metadata"]["sha256"]) == 64
assert len(manifest["immutable_artifacts"]["partition_metadata"]["sha256"]) == 64
assert (
    manifest["normalized_manifests"]["partition_metadata"]["format_version"]
    == "mkosi-partition-metadata-v1"
)
assert len(manifest["immutable_artifacts"]["raw_image"]["canonical_sha256"]) == 64
assert manifest["normalized_manifests"]["build_metadata"]["mode"] == "release"
