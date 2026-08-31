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
        "f68b7731ba8c3f02cc4f52e68ec2ddfa225a3c796afc64af8cd8b6fe4d4faca7",
        info.lock_sha256,
    )
    asserts.equals(env, "repository_repository", info.repository.basename)
    asserts.equals(env, "inrelease", info.inrelease.basename)
    asserts.equals(env, 135, len(info.package_files.to_list()))
    actions = analysistest.target_actions(env)
    asserts.equals(env, 1, len(actions))
    asserts.equals(env, "StageDebianSnapshot", actions[0].mnemonic)
    asserts.equals(env, 2, len(actions[0].outputs.to_list()))
    return analysistest.end(env)

debian_snapshot_provider_test = analysistest.make(_provider_test_impl)
