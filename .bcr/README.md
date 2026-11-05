# Bazel Central Registry publishing

The files in this directory are templates for [`bazel-contrib/publish-to-bcr`](https://github.com/bazel-contrib/publish-to-bcr).
Pushing a `v*.*.*` tag runs [`release.yml`](../.github/workflows/release.yml), which:

1. Builds `rules_mkosi-<tag>.tar.gz` with [`release_prep.sh`](../.github/workflows/release_prep.sh), attests it, and uploads it to a draft GitHub release.
2. Runs [`publish.yml`](../.github/workflows/publish.yml), which generates the registry entry from these templates, attests it, pushes it to the registry fork, and opens a draft pull request against [`bazelbuild/bazel-central-registry`](https://github.com/bazelbuild/bazel-central-registry).
3. Publishes the draft GitHub release.

## One-time setup

1. Fork `bazelbuild/bazel-central-registry` to `maxbirkner/bazel-central-registry`, the `registry_fork` in `publish.yml`.
2. Create a classic personal access token with the `repo` and `workflow` scopes for the fork owner.
3. Save it as the `BCR_PUBLISH_TOKEN` Actions secret of this repository.
4. Optionally, restrict who can create `v*` tags with a tag ruleset.

## Releasing

1. Pick a commit on `main` whose `CI conclusion` passed.
2. Tag and push it, for example `git tag v0.1.0 <commit> && git push origin v0.1.0`.
3. Wait for the BCR presubmit on the draft pull request, then mark it ready for review; as a listed maintainer, that approves the entry.

If publishing fails after the archive was uploaded, fix the cause and run `publish.yml` manually with the tag and the ID of the failed `Release` run.
Never replace an uploaded archive, because the registry entry pins its integrity.

## Presubmit

BCR runners cannot be assumed to provide user namespaces, a group-free Bazel server, or access to snapshot.debian.org, so `presubmit.yml` runs only `//:stock_runner_tests` of [`e2e/smoke`](../e2e/smoke).
[`ci/bcr-presubmit.sh`](../ci/bcr-presubmit.sh) runs the same suite in CI from a source archive under those limits.
The default Bazel version checks the committed lockfile strictly, and `ci/check_bazel_versions.py` keeps the task versions in sync with `ci/bazel_versions.json`.
