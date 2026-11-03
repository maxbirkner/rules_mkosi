"""Repository rule for authenticated Debian snapshot metadata."""

load(":sha256.bzl", "sha256_hex")

_HEX = "0123456789abcdef"
_IDENTIFIER_CHARACTERS = "abcdefghijklmnopqrstuvwxyz0123456789-"
_INDEX_ARCHITECTURES = ["amd64", "all"]

def _is_sha256(value):
    return type(value) == type("") and len(value) == 64 and value.strip(_HEX) == ""

def _is_identifier(value):
    return (
        type(value) == type("") and
        value != "" and
        value[0] != "-" and
        value.strip(_IDENTIFIER_CHARACTERS) == ""
    )

def index_name(component, architecture):
    """Returns the lock metadata name of a component's Packages.xz index.

    The main component keeps the original single-component names so existing
    locks remain valid without migration.
    """
    prefix = "" if component == "main" else component + "_"
    return prefix + ("packages_xz" if architecture == "amd64" else "packages_all_xz")

def _validate_snapshot(repository):
    """Returns the immutable snapshot identifier and URL of the lock."""
    snapshot_url = repository.get("snapshot_url", "")
    snapshot = repository.get("snapshot", "")
    if not snapshot or len(snapshot) != 16 or snapshot[-1] != "Z" or "T" not in snapshot:
        fail("Debian snapshot must be an immutable UTC timestamp")
    if not snapshot_url.startswith("https://") or not snapshot_url.endswith("/" + snapshot):
        fail("Debian snapshot URL must end with its immutable snapshot identifier")
    return snapshot, snapshot_url

def _validate_release(repository):
    """Returns the codename and numeric release of the lock."""
    if repository.get("distribution", "debian") != "debian":
        fail("Debian lock distribution must be debian")
    if repository.get("architecture", "amd64") != "amd64":
        fail("Debian lock architecture must be amd64")
    codename = repository.get("codename", "trixie")
    if not _is_identifier(codename):
        fail("Debian lock codename is invalid: %s" % codename)
    release = repository.get("release", "13")
    if type(release) != type("") or not release.isdigit():
        fail("Debian lock release must be numeric")
    return codename, release

def _validate_components(repository):
    """Returns the locked components, starting with main."""
    components = repository.get("components", ["main"])
    if type(components) != type([]) or "main" not in components:
        fail("Debian lock components must include main")
    for component in components:
        if not _is_identifier(component):
            fail("Debian lock component is invalid: %s" % component)
    if len(set(components)) != len(components):
        fail("Debian lock components must be unique")
    return ["main"] + [component for component in components if component != "main"]

def _expected_metadata(codename, components):
    """Returns (path, component, architecture) of every required metadata entry, keyed by name."""
    dists = "dists/" + codename
    expected = {
        "inrelease": (dists + "/InRelease", None, None),
        "release": (dists + "/Release", None, None),
        "release_gpg": (dists + "/Release.gpg", None, None),
    }
    for component in components:
        for architecture in _INDEX_ARCHITECTURES:
            expected[index_name(component, architecture)] = (
                "%s/%s/binary-%s/Packages.xz" % (dists, component, architecture),
                component,
                architecture,
            )
    return expected

def _validate_metadata_entry(entry, expected, snapshot_url):
    name = entry.get("name", "")
    path = entry.get("path", "")
    if name not in expected:
        fail("unexpected Debian repository metadata: %s" % name)
    if not path or path.startswith("/") or ".." in path.split("/"):
        fail("unsafe Debian repository metadata path: %s" % path)
    expected_path, component, architecture = expected[name]
    if path != expected_path:
        fail("Debian repository metadata %s must use path %s" % (name, expected_path))
    if entry.get("component", component) != component or entry.get("architecture", architecture) != architecture:
        fail("Debian repository metadata %s has an inconsistent component or architecture" % name)
    if entry.get("url", "") != snapshot_url + "/" + path:
        fail("Debian repository metadata URL is outside the pinned snapshot: %s" % entry.get("url", ""))
    if not _is_sha256(entry.get("sha256", "")):
        fail("Debian repository metadata digest is not SHA-256: %s" % path)

def _validate_metadata(repository, expected, snapshot_url):
    """Returns the repository metadata entries after checking that they pin exactly the expected files."""
    metadata = repository.get("metadata", [])
    if not metadata:
        fail("Debian lock has no repository metadata")
    names = set()
    for entry in metadata:
        name = entry.get("name", "")
        if not name or name in names:
            fail("Debian repository metadata names must be unique")
        names.add(name)
        _validate_metadata_entry(entry, expected, snapshot_url)
    if names != set(expected.keys()):
        fail("Debian repository metadata must pin all required indexes and signatures")
    return metadata

def _validate_package_file(package, snapshot_url):
    filename = package.get("filename", "")
    parts = filename.split("/")
    if not filename.startswith("pool/") or ".." in parts or "." in parts or "" in parts:
        fail("unsafe Debian package filename: %s" % filename)
    if not filename.endswith(".deb"):
        fail("Debian package filename is not a .deb: %s" % filename)
    if package.get("urls", []) != [snapshot_url + "/" + filename]:
        fail("Debian package URL does not match filename: %s" % filename)
    size = package.get("size")
    if type(size) != type(0) or size < 0 or not _is_sha256(package.get("sha256", "")):
        fail("Debian package lock has invalid size or digest: %s" % filename)

def _validate_packages(lock, snapshot_url, components):
    package_keys = set()
    lock_keys = set()
    for package in lock.get("packages", []):
        name = package.get("name", "")
        architecture = package.get("arch", "")
        if not name or not package.get("version", "") or architecture not in _INDEX_ARCHITECTURES:
            fail("Debian package lock has incomplete identity")
        _validate_package_file(package, snapshot_url)
        lock_key = package.get("key", "")
        if type(lock_key) != type("") or not lock_key or lock_key in lock_keys:
            fail("Debian package lock keys must be unique: %s" % package.get("filename", ""))
        lock_keys.add(lock_key)
        if package.get("component", "main") not in components:
            fail("Debian package %s is not in a locked component" % name)
        key = (name, package.get("version", ""), architecture)
        if key in package_keys:
            fail("duplicate Debian package lock identity: %s" % name)
        package_keys.add(key)

def validate_lock(lock):
    """Validates a Debian snapshot lock and returns its normalized identity.

    Fails on any malformed, unpinned, or unsafe repository metadata or package
    record. A lock without repository.components is a main-only lock.

    Args:
      lock: Decoded lock JSON.

    Returns:
      A struct with the codename, components (main first), distribution,
      architecture, metadata entries, release, snapshot, and snapshot URL.
    """
    repository = lock.get("repository")
    if not repository:
        fail("Debian lock is missing repository metadata")
    snapshot, snapshot_url = _validate_snapshot(repository)
    codename, release = _validate_release(repository)
    components = _validate_components(repository)
    metadata = _validate_metadata(repository, _expected_metadata(codename, components), snapshot_url)
    _validate_packages(lock, snapshot_url, components)
    return struct(
        codename = codename,
        components = components,
        distribution = "debian",
        architecture = "amd64",
        metadata = metadata,
        release = release,
        snapshot = snapshot,
        snapshot_url = snapshot_url,
    )

_BUILD_TEMPLATE = """load("@rules_mkosi//mkosi:defs.bzl", "debian_snapshot")

package(default_visibility = ["//visibility:public"])

exports_files({files})

debian_snapshot(
    name = "repository",
    distribution = {distribution},
    release = {release},
    codename = {codename},
    architecture = {architecture},
    snapshot = {snapshot},
    snapshot_url = {snapshot_url},
    lock_sha256 = {lock_sha256},
    inrelease = ":inrelease",
    release_metadata = ":release",
    release_gpg = ":release_gpg",
    packages_xz = ":packages_xz",
    packages_all_xz = ":packages_all_xz",
    packages_path = {packages_path},
    packages_all_path = {packages_all_path},
    component_packages = {component_packages},
    component_package_records = {component_package_records},
    package_files = ["{package_repo}//:all"],
    package_names = {package_names},
    package_records = {package_records},
    metadata_digests = {digests},
)
"""

_MAIN_METADATA = ["inrelease", "release", "release_gpg", "packages_xz", "packages_all_xz"]

def _read_lock(ctx):
    """Returns the lock content and its SHA-256 after checking the optional expected digest."""
    content = ctx.read(ctx.attr.lock)
    lock_sha256 = sha256_hex(content)
    if ctx.attr.lock_sha256 and lock_sha256 != ctx.attr.lock_sha256:
        fail("Debian lock %s has SHA-256 %s, expected %s" % (
            ctx.attr.lock,
            lock_sha256,
            ctx.attr.lock_sha256,
        ))
    return content, lock_sha256

def _download_metadata(ctx, metadata):
    """Downloads every metadata entry to a file named after it and returns the entries by name."""
    entries = {}
    for entry in metadata:
        ctx.download(
            url = entry["url"],
            output = entry["name"],
            sha256 = entry["sha256"],
            canonical_id = entry["url"] + "#" + entry["sha256"],
        )
        entries[entry["name"]] = entry
    return entries

def locked_packages(lock):
    """Returns the packages of a decoded lock in the order of their repository-local file names."""
    return sorted(lock["packages"], key = lambda package: package["key"])

def local_package_name(index):
    """Returns the repository-local file name of a locked package.

    Args:
      index: Position of the package in locked_packages.

    Returns:
      The file name, such as pkg_007.deb.
    """
    index_string = str(index)
    if index < 10:
        index_string = "00" + index_string
    elif index < 100:
        index_string = "0" + index_string
    return "pkg_" + index_string + ".deb"

def _package_records(lock):
    """Returns the local file names and debian_snapshot records of the locked packages."""
    names = []
    records = []
    for index, package in enumerate(locked_packages(lock)):
        local_name = local_package_name(index)
        names.append(local_name)
        records.append("%s|%s|%s|%s|%s|%s|%s" % (
            package["name"],
            package["version"],
            package["arch"],
            package["filename"],
            package["size"],
            package["sha256"],
            local_name,
        ))
    return names, records

def _component_indexes(components, entries):
    """Returns the labels and debian_snapshot records of the Packages.xz indexes of components other than main."""
    labels = []
    records = []
    for component in components[1:]:
        for architecture in _INDEX_ARCHITECTURES:
            entry = entries[index_name(component, architecture)]
            labels.append(":" + entry["name"])
            records.append("|".join([component, architecture, entry["path"], entry["sha256"]]))
    return labels, records

def _impl(ctx):
    content, lock_sha256 = _read_lock(ctx)
    ctx.file("lock.json", content, executable = False, legacy_utf8 = False)
    repository = validate_lock(json.decode(content))
    entries = _download_metadata(ctx, repository.metadata)
    package_names, package_records = _package_records(json.decode(content))
    component_packages, component_package_records = _component_indexes(repository.components, entries)
    ctx.file("BUILD.bazel", _BUILD_TEMPLATE.format(
        files = repr(sorted(entries.keys()) + ["lock.json"]),
        distribution = repr(repository.distribution),
        release = repr(repository.release),
        codename = repr(repository.codename),
        architecture = repr(repository.architecture),
        snapshot = repr(repository.snapshot),
        snapshot_url = repr(repository.snapshot_url),
        lock_sha256 = repr(lock_sha256),
        package_repo = ctx.attr.package_repo,
        package_records = repr(package_records),
        package_names = repr(package_names),
        digests = repr({name: entries[name]["sha256"] for name in _MAIN_METADATA}),
        packages_path = repr(entries["packages_xz"]["path"]),
        packages_all_path = repr(entries["packages_all_xz"]["path"]),
        component_packages = repr(component_packages),
        component_package_records = repr(component_package_records),
    ))
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_snapshot_repo = repository_rule(
    implementation = _impl,
    attrs = {
        "lock": attr.label(mandatory = True, allow_single_file = True),
        "package_repo": attr.string(mandatory = True),
        "lock_sha256": attr.string(
            doc = "Optional expected SHA-256 of the lock file. The computed digest is always recorded.",
        ),
    },
)
