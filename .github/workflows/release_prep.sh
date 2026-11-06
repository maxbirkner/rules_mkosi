#!/usr/bin/env bash
# Builds the release archive for a tag and prints the release notes.
# The reusable bazel-contrib release workflow runs this script from this fixed path with the tag as its only argument.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: release_prep.sh TAG" >&2
  exit 2
fi

tag="$1"
if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "release tags look like v1.2.3; prereleases are not supported, not $tag" >&2
  exit 1
fi
version="${tag#v}"
prefix="rules_mkosi-$version"
archive="rules_mkosi-$tag.tar.gz"

# The BCR source.json points at this asset, so its content must never change after upload. Its prefix matches
# GitHub's generated source archives, and .gitattributes stamps the tag into mkosi/version.bzl.
git archive --format=tar --prefix="$prefix/" "$tag" | gzip -n >"$archive"

stamped="$(tar -xzOf "$archive" "$prefix/mkosi/version.bzl")"
if ! grep -Fqx "_VERSION_PRIVATE = \"$tag\"" <<<"$stamped"; then
  echo "$archive: mkosi/version.bzl is not stamped with $tag" >&2
  exit 1
fi

# The BCR source.json's docs_url points at this asset: Stardoc's extracted API documentation, which the registry
# renders. Bazel prints everything but the queried labels and the info path to stderr, keeping stdout for the notes.
docs_archive="rules_mkosi-$tag.docs.tar.gz"
mapfile -t doc_targets < <(bazel query --output=label 'kind("starlark_doc_extract rule", //docs/api:all)')
bazel build "${doc_targets[@]}"
bazel_bin="$(bazel info bazel-bin)"
(cd "$bazel_bin" && find docs -name '*.binaryproto' -print0 | LC_ALL=C sort -z |
  tar --create --null --files-from=- --owner=0 --group=0 --numeric-owner --mtime=@0) | gzip -n >"$docs_archive"

cat <<EOF
## Using rules_mkosi

Add to your \`MODULE.bazel\`:

\`\`\`starlark
bazel_dep(name = "rules_mkosi", version = "$version")
\`\`\`

See the [setup instructions](https://github.com/maxbirkner/rules_mkosi/blob/$tag/README.md#setup) for the host requirements and the toolchain registration.
EOF
