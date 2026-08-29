---
name: bcr-release
description: Prepare, validate, and publish a rules_mkosi release to the Bazel Central Registry using stable release assets and the repository's BCR templates.
license: Apache-2.0
---

# Release rules_mkosi to the BCR

Use this workflow only for release preparation and Bazel Central Registry
publication.

1. Read the current BCR contribution guide and
   `docs/design/0003-ruleset-architecture.md`; registry requirements can
   change.
2. Confirm the release is compatible with every Bazel major declared in
   `MODULE.bazel` by running root and `e2e/smoke` tests.
3. Confirm all generated API documentation and both lockfiles are current.
4. Choose the semantic version from merged pull requests and compatibility
   impact. Keep the source-tree `module()` version unset; the BCR publisher
   patches the registry copy.
5. Create a deterministic source archive named
   `rules_mkosi-v<version>.tar.gz` with top-level prefix
   `rules_mkosi-<version>/`.
6. Upload the archive as an immutable GitHub release asset. Do not use
   GitHub's automatically generated tag archive as the BCR source URL.
7. Keep `e2e/smoke` in the archive because `.bcr/presubmit.yml` declares it as
   `bcr_test_module.module_path`.
8. Generate the BCR entry from `.bcr/metadata.template.json`,
   `.bcr/source.template.json`, and `.bcr/presubmit.yml`.
9. Verify the source integrity, archive prefix, repository allowlist, module
   name, module version, dependency graph, and per-task Bazel versions.
10. Validate the generated entry with the BCR validation tooling before
    opening its pull request.
11. Use `bazel-contrib/.github` `release_ruleset` if build-provenance
    attestations are enabled. BCR currently rejects incompatible custom
    attestation formats.
12. Keep the GitHub release in draft while attested assets and the BCR pull
    request are created, then finalize it.
Never mutate or replace a published release asset. BCR is add-only; correct a
registry-only defect with the registry's `.bcr.N` version mechanism.
registry-only defect with the registry's `.bcr.N` version mechanism.
