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
assert (
    manifest["normalized_manifests"]["raw_image"]["root_partition"]["type_uuid"]
    == "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
)
assert manifest["normalized_manifests"]["build_metadata"]["mode"] == "release"
