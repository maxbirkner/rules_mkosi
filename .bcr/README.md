# Bazel Central Registry publishing

The files in this directory are templates consumed by
[`bazel-contrib/publish-to-bcr`](https://github.com/bazel-contrib/publish-to-bcr).

Before the first release:

1. Configure the `BCR_PUBLISH_TOKEN` repository secret.
2. Add the bazel-contrib release and publish workflows.
3. Produce a stable release-asset archive rather than relying on GitHub's
   automatically generated source archive.
4. Keep `e2e/smoke` in the release archive because BCR executes it as the test
   module.
5. Validate the generated registry entry with the BCR validation tool.

See [the release design](../docs/design/0003-ruleset-architecture.md) for the
full process and the reasons release automation is intentionally deferred.
