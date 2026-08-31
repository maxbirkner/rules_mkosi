"""Repository rule for authenticated Debian snapshot metadata."""

def _validate_lock(lock):
    repository = lock.get("repository")
    if not repository:
        fail("Debian lock is missing repository metadata")
    snapshot_url = repository.get("snapshot_url", "")
    snapshot = repository.get("snapshot", "")
    if not snapshot or len(snapshot) != 16 or snapshot[-1] != "Z" or "T" not in snapshot:
        fail("Debian snapshot must be an immutable UTC timestamp")
    if not snapshot_url.endswith(snapshot):
        fail("Debian snapshot URL must end with its immutable snapshot identifier")
    metadata = repository.get("metadata", [])
    if not metadata:
        fail("Debian lock has no repository metadata")
    names = set()
    for entry in metadata:
        name = entry.get("name", "")
        path = entry.get("path", "")
        digest = entry.get("sha256", "")
        url = entry.get("url", "")
        if not name or name in names:
            fail("Debian repository metadata names must be unique")
        names.add(name)
        if not path or path.startswith("/") or ".." in path.split("/"):
            fail("unsafe Debian repository metadata path: %s" % path)
        if not url.startswith(snapshot_url + "/"):
            fail("Debian repository metadata URL is outside the pinned snapshot: %s" % url)
        invalid_digest = digest.strip("0123456789abcdef") != ""
        if len(digest) != 64 or invalid_digest:
            fail("Debian repository metadata digest is not SHA-256: %s" % path)
    if names != set(["inrelease", "release", "release_gpg", "packages_xz", "packages_all_xz"]):
        fail("Debian repository metadata must pin all required indexes and signatures")
    return repository

def _impl(ctx):
    lock = json.decode(ctx.read(ctx.attr.lock))
    repository = _validate_lock(lock)
    files = []
    for entry in repository["metadata"]:
        output = entry["name"]
        ctx.download(
            url = entry["url"],
            output = output,
            sha256 = entry["sha256"],
            canonical_id = entry["url"] + "#" + entry["sha256"],
        )
        files.append((entry["name"], output))

    packages = sorted(lock["packages"], key = lambda package: package["key"])
    package_records = []
    package_names = []
    for index, package in enumerate(packages):
        filename = package["urls"][0].split(repository["snapshot_url"] + "/", 1)[-1]
        index_string = str(index)
        if index < 10:
            index_string = "00" + index_string
        elif index < 100:
            index_string = "0" + index_string
        local_name = "pkg_" + index_string + ".deb"
        package_names.append(local_name)
        package_records.append("%s|%s|%s|%s|%s|%s" % (
            package["name"],
            package["version"],
            "all" if filename.endswith("_all.deb") else package["arch"],
            filename,
            package["sha256"],
            local_name,
        ))
    digests = {
        entry["name"]: entry["sha256"]
        for entry in repository["metadata"]
    }
    ctx.file(
        "BUILD.bazel",
        """load("@rules_mkosi//mkosi:defs.bzl", "debian_snapshot")

package(default_visibility = ["//visibility:public"])

exports_files({files})

debian_snapshot(
    name = "repository",
    snapshot = {snapshot},
    snapshot_url = {snapshot_url},
    lock_sha256 = {lock_sha256},
    inrelease = ":inrelease",
    release_metadata = ":release",
    release_gpg = ":release_gpg",
    packages_xz = ":packages_xz",
    packages_all_xz = ":packages_all_xz",
    package_files = ["{package_repo}//:all"],
    package_names = {package_names},
    package_records = {package_records},
    metadata_digests = {digests},
)
""".format(
            files = repr([output for _, output in files]),
            snapshot = repr(repository["snapshot"]),
            snapshot_url = repr(repository["snapshot_url"]),
            lock_sha256 = repr(ctx.attr.lock_sha256),
            package_repo = ctx.attr.package_repo,
            package_records = repr(package_records),
            package_names = repr(package_names),
            digests = repr(digests),
        ),
    )
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_snapshot_repo = repository_rule(
    implementation = _impl,
    attrs = {
        "lock": attr.label(mandatory = True, allow_single_file = True),
        "package_repo": attr.string(mandatory = True),
        "lock_sha256": attr.string(mandatory = True),
    },
)
