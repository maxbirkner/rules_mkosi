"""Analysis coverage for the public Debian snapshot rule."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "DebianSnapshotInfo")

def _provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, DebianSnapshotInfo in target)
    info = target[DebianSnapshotInfo]
    asserts.equals(env, "debian-snapshot-v1", info.format_version)
    asserts.equals(env, "debian", info.distribution)
    asserts.equals(env, "13", info.release)
    asserts.equals(env, "trixie", info.codename)
    asserts.equals(env, "amd64", info.architecture)
    asserts.equals(env, "20250814T000000Z", info.snapshot)
    asserts.equals(
        env,
        "https://snapshot.debian.org/archive/debian/20250814T000000Z",
        info.snapshot_url,
    )
    asserts.equals(
        env,
        "fa4e9f106cf6fb20b8b2c2b9206375e4af25abb7fd885fbfd9613ecb7bb191ce",
        info.lock_sha256,
    )
    asserts.equals(env, "repository_repository", info.repository.basename)
    asserts.equals(env, "inrelease", info.inrelease.basename)
    asserts.equals(env, 191, len(info.package_files.to_list()))
    actions = analysistest.target_actions(env)
    asserts.equals(env, 1, len(actions))
    asserts.equals(env, "StageDebianSnapshot", actions[0].mnemonic)
    asserts.equals(env, 2, len(actions[0].outputs.to_list()))
    return analysistest.end(env)

debian_snapshot_provider_test = analysistest.make(_provider_test_impl)
