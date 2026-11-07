"""Repository rule for the Secure Boot capable OVMF that qemu_ovmf_boot_test(secure_boot = True) boots.

Only Secure Boot boot tests depend on the repository, so other builds never download it.
"""

load("//mkosi:qemu_versions.bzl", "OVMF_SECURE_BOOT_SHA256", "OVMF_SECURE_BOOT_URLS", "OVMF_SECURE_BOOT_VERSION")

_FILES = ["OVMF_CODE_4M.secboot.fd", "OVMF_VARS_4M.fd"]

_BUILD = """package(default_visibility = ["//visibility:public"])

exports_files({files})

# Debian ovmf {version}
"""

def _ovmf_secure_boot_repo_impl(repository_ctx):
    repository_ctx.download_and_extract(
        url = OVMF_SECURE_BOOT_URLS,
        sha256 = OVMF_SECURE_BOOT_SHA256,
        type = "deb",
        output = "deb",
    )
    repository_ctx.extract("deb/data.tar.xz", output = "data")
    for name in _FILES:
        repository_ctx.symlink("data/usr/share/OVMF/" + name, name)
    repository_ctx.delete("deb")
    repository_ctx.file("BUILD.bazel", _BUILD.format(files = repr(_FILES), version = OVMF_SECURE_BOOT_VERSION))
    if hasattr(repository_ctx, "repo_metadata"):
        return repository_ctx.repo_metadata(reproducible = True)
    return None

ovmf_secure_boot_repo = repository_rule(
    implementation = _ovmf_secure_boot_repo_impl,
    doc = "Fetches OVMF_CODE_4M.secboot.fd and its empty OVMF_VARS_4M.fd from the pinned Debian ovmf package.",
)
