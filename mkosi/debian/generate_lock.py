"""Generate a rules_mkosi Debian snapshot lock from a package specification.

The specification is JSON with the same shape as ``debian13.yaml``:

    {
      "version": 1,
      "sources": [
        {
          "channel": "trixie main non-free-firmware",
          "url": "https://snapshot.debian.org/archive/debian/20250814T000000Z"
        }
      ],
      "archs": ["amd64"],
      "packages": ["amd64-microcode"]
    }

The generator downloads the snapshot's InRelease, Release, and Release.gpg,
checks that InRelease carries the same Release payload, verifies every
component's binary-amd64 and binary-all Packages.xz against the Release
SHA-256 list, and resolves the Depends and Pre-Depends closure of the requested
packages plus every Essential and Priority: required package. Recommends and
Suggests are not followed. Signatures are verified by the build-time staging
action with Debian's pinned archive keyring, so a tampered index fails the
build even if it was accepted here.
"""

import argparse
import collections
import dataclasses
import functools
import hashlib
import json
import lzma
import os
import pathlib
import re
import runpy
import sys
import time
import urllib.error
import urllib.request

ARCHITECTURE = "amd64"
INDEX_ARCHITECTURES = (ARCHITECTURE, "all")

_SNAPSHOT = re.compile(r"[0-9]{8}T[0-9]{6}Z")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]*")
_PACKAGE_NAME = re.compile(r"[a-z0-9][a-z0-9+.-]+")
_RELATION = re.compile(
    r"(?P<name>[a-z0-9][a-z0-9+.-]+)"
    r"(?::(?P<arch>[a-z0-9-]+))?"
    r"\s*(?:\(\s*(?P<op><<|<=|=|>=|>>|<|>)\s*(?P<version>[^\s)]+)\s*\))?"
    r"\s*(?:\[[^\]]*\])?"
    r"\s*(?:<[^>]*>\s*)*"
)
_PRIORITY_RANK = {"required": 0, "important": 1, "standard": 2, "optional": 3, "extra": 4}


class LockError(Exception):
    """A specification, snapshot, or dependency closure cannot be locked."""


# The Debian snapshot staging action parses the same Packages indexes with this parser.
_parse_paragraphs = runpy.run_path(
    os.path.join(os.path.dirname(__file__), os.pardir, "private", "debian_control.py")
)["paragraphs"]


def _order(character):
    if character == "~":
        return -1
    if character.isdigit():
        return 0
    if character.isalpha():
        return ord(character)
    return ord(character) + 256


def _compare_non_digits(left, right, left_index, right_index):
    """Compares the non-digit prefixes at the indexes; returns the difference and the indexes after them."""
    while (left_index < len(left) and not left[left_index].isdigit()) or (
        right_index < len(right) and not right[right_index].isdigit()
    ):
        left_order = _order(left[left_index]) if left_index < len(left) else 0
        right_order = _order(right[right_index]) if right_index < len(right) else 0
        if left_order != right_order:
            return left_order - right_order, left_index, right_index
        left_index += 1
        right_index += 1
    return 0, left_index, right_index


def _compare_digits(left, right, left_index, right_index):
    """Numerically compares the digit runs at the indexes; returns the difference and the indexes after them."""
    while left_index < len(left) and left[left_index] == "0":
        left_index += 1
    while right_index < len(right) and right[right_index] == "0":
        right_index += 1
    difference = 0
    while (
        left_index < len(left)
        and left[left_index].isdigit()
        and right_index < len(right)
        and right[right_index].isdigit()
    ):
        if not difference:
            difference = ord(left[left_index]) - ord(right[right_index])
        left_index += 1
        right_index += 1
    if left_index < len(left) and left[left_index].isdigit():
        return 1, left_index, right_index
    if right_index < len(right) and right[right_index].isdigit():
        return -1, left_index, right_index
    return difference, left_index, right_index


def _compare_fragment(left, right):
    left_index = 0
    right_index = 0
    while left_index < len(left) or right_index < len(right):
        for compare in (_compare_non_digits, _compare_digits):
            difference, left_index, right_index = compare(left, right, left_index, right_index)
            if difference:
                return difference
    return 0


def _split_version(version):
    epoch = 0
    if ":" in version:
        epoch_text, version = version.split(":", 1)
        if not epoch_text.isdigit():
            raise LockError("invalid Debian version epoch: %s" % epoch_text)
        epoch = int(epoch_text)
    upstream, separator, revision = version.rpartition("-")
    if not separator:
        upstream, revision = revision, ""
    return epoch, upstream, revision


def compare_versions(left, right):
    """Compare two Debian versions with dpkg semantics.

    Returns a negative number, zero, or a positive number when ``left`` sorts
    before, equal to, or after ``right``.
    """
    left_epoch, left_upstream, left_revision = _split_version(left)
    right_epoch, right_upstream, right_revision = _split_version(right)
    if left_epoch != right_epoch:
        return left_epoch - right_epoch
    return _compare_fragment(left_upstream, right_upstream) or _compare_fragment(
        left_revision, right_revision
    )


_RELATION_OPERATORS = {
    "<<": lambda result: result < 0,
    "<=": lambda result: result <= 0,
    "<": lambda result: result <= 0,
    "=": lambda result: result == 0,
    ">=": lambda result: result >= 0,
    ">": lambda result: result >= 0,
    ">>": lambda result: result > 0,
}


def version_satisfies(version, operator, required):
    """Return whether ``version`` satisfies the relation ``operator required``."""
    result = compare_versions(version, required)
    if operator not in _RELATION_OPERATORS:
        raise LockError("unsupported version relation: %s" % operator)
    return _RELATION_OPERATORS[operator](result)


@dataclasses.dataclass(frozen=True)
class Relation:
    """One alternative of a Debian dependency field."""

    name: str
    arch: str | None = None
    operator: str | None = None
    version: str | None = None

    def __str__(self):
        text = self.name + (":" + self.arch if self.arch else "")
        if self.operator:
            text += " (%s %s)" % (self.operator, self.version)
        return text


def parse_relations(value):
    """Parse a Depends-style field into a list of alternative groups."""
    groups = []
    for group_text in (value or "").replace("\n", " ").split(","):
        if not group_text.strip():
            continue
        group = []
        for alternative in group_text.split("|"):
            match = _RELATION.fullmatch(alternative.strip())
            if not match:
                raise LockError("malformed Debian relation: %s" % alternative.strip())
            group.append(
                Relation(
                    match.group("name"),
                    match.group("arch"),
                    match.group("op"),
                    match.group("version"),
                )
            )
        groups.append(tuple(group))
    return tuple(groups)


def parse_provides(value):
    provides = []
    for group in parse_relations(value):
        if len(group) != 1:
            raise LockError("Provides cannot contain alternatives")
        relation = group[0]
        if relation.operator not in (None, "="):
            raise LockError("Provides may only use exact versions: %s" % relation)
        provides.append((relation.name, relation.version))
    return tuple(provides)


def paragraphs(text):
    """Parse deb822 control data into ordered dictionaries; raises LockError for malformed data."""
    try:
        return _parse_paragraphs(text)
    except ValueError as error:
        raise LockError(str(error)) from None


@dataclasses.dataclass(frozen=True)
class Package:
    """A binary package record from an authenticated Packages index."""

    name: str
    version: str
    architecture: str
    component: str
    filename: str
    size: int
    sha256: str
    multi_arch: str = "no"
    essential: bool = False
    priority: str = "optional"
    pre_depends: tuple = ()
    depends: tuple = ()
    provides: tuple = ()

    @property
    def key(self):
        return lock_key(self.name, self.version, self.architecture)


def lock_key(name, version, architecture):
    """Return the filesystem-safe lock key used to order staged packages."""
    return "%s_%s_%s" % (
        name.replace("+", "-p-"),
        version.replace(":", "-").replace("+", "-p-").replace("~", "-t-"),
        architecture,
    )


def _package_record(paragraph, component, index_architecture):
    architecture = paragraph.get("Architecture")
    if architecture not in INDEX_ARCHITECTURES:
        raise LockError("unsupported package architecture: %s" % architecture)
    if index_architecture == "all" and architecture != "all":
        raise LockError("binary-all index contains non-all package")
    size = paragraph.get("Size", "")
    digest = paragraph.get("SHA256", "")
    filename = paragraph.get("Filename", "")
    if (
        not paragraph.get("Package")
        or not paragraph.get("Version")
        or not size.isdigit()
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not filename.startswith("pool/")
    ):
        raise LockError("incomplete package metadata: %s" % paragraph.get("Package"))
    return Package(
        name=paragraph["Package"],
        version=paragraph["Version"],
        architecture=architecture,
        component=component,
        filename=filename,
        size=int(size),
        sha256=digest,
        multi_arch=paragraph.get("Multi-Arch", "no"),
        essential=paragraph.get("Essential") == "yes",
        priority=paragraph.get("Priority", "optional"),
        pre_depends=parse_relations(paragraph.get("Pre-Depends")),
        depends=parse_relations(paragraph.get("Depends")),
        provides=parse_provides(paragraph.get("Provides")),
    )


def parse_packages(text, component, index_architecture):
    """Parse one Packages index into Package records."""
    return [_package_record(paragraph, component, index_architecture) for paragraph in paragraphs(text)]


class Universe:
    """Installable single-architecture view of the locked components."""

    def __init__(self, packages):
        by_name = collections.defaultdict(dict)
        for package in packages:
            identity = (package.version, package.architecture)
            previous = by_name[package.name].get(identity)
            if previous is None:
                by_name[package.name][identity] = package
            elif previous != dataclasses.replace(package, component=previous.component):
                raise LockError("conflicting duplicate package metadata: %s" % package.name)
        newest_first = functools.cmp_to_key(lambda left, right: compare_versions(right.version, left.version))
        self._packages = {}
        self._providers = collections.defaultdict(list)
        for name, candidates in by_name.items():
            ordered = tuple(sorted(candidates.values(), key=newest_first))
            self._packages[name] = ordered
            for package in ordered:
                for provided, version in package.provides:
                    self._providers[provided].append((package, version))
        for providers in self._providers.values():
            providers.sort(
                key=lambda entry: (
                    _PRIORITY_RANK.get(entry[0].priority, len(_PRIORITY_RANK)),
                    entry[0].name,
                )
            )

    def packages(self):
        for candidates in self._packages.values():
            yield from candidates

    def newest(self, name):
        candidates = self._packages.get(name, ())
        return candidates[0] if candidates else None

    @staticmethod
    def _architecture_matches(package, qualifier):
        # Only the native architecture is resolved, so dpkg's Multi-Arch rules reduce to this: an
        # unqualified, :any, or native-qualified relation accepts native and arch: all packages, while a
        # foreign architecture qualifier is satisfied only by Multi-Arch: foreign packages.
        if qualifier in (None, "any", "native", ARCHITECTURE):
            return package.architecture in INDEX_ARCHITECTURES
        return package.multi_arch == "foreign"

    def candidates(self, relation):
        """Return packages satisfying ``relation`` in apt's preference order."""
        result = []
        for package in self._packages.get(relation.name, ()):
            if self._architecture_matches(package, relation.arch) and (
                not relation.operator
                or version_satisfies(package.version, relation.operator, relation.version)
            ):
                result.append(package)
        for package, provided_version in self._providers.get(relation.name, ()):
            if not self._architecture_matches(package, relation.arch) or package in result:
                continue
            if relation.operator and (
                provided_version is None
                or not version_satisfies(provided_version, relation.operator, relation.version)
            ):
                continue
            result.append(package)
        return result


def _format_group(group):
    return " | ".join(str(relation) for relation in group)


class _Closure:
    """Packages selected so far, the dependency edges between them, and those whose dependencies are pending."""

    def __init__(self):
        self.selected = {}
        self.edges = {}
        self.queue = collections.deque()

    def select(self, package, reason):
        current = self.selected.get(package.name)
        if current is not None:
            if current != package:
                raise LockError(
                    "%s requires %s %s, but %s is already selected"
                    % (reason, package.name, package.version, current.version)
                )
            return
        self.selected[package.name] = package
        self.edges[package.name] = set()
        self.queue.append(package)


def _select_bootstrap(universe, closure):
    bootstrap = sorted(
        {
            package.name
            for package in universe.packages()
            if package.essential or package.priority == "required"
        }
    )
    for name in bootstrap:
        closure.select(universe.newest(name), "the bootstrap set")


def _select_requested(universe, requested, closure):
    missing = []
    for name in requested:
        candidates = universe.candidates(Relation(name))
        real = [package for package in candidates if package.name == name]
        if real:
            closure.select(real[0], "the specification")
        elif len(candidates) == 1:
            closure.select(candidates[0], "the specification")
        elif candidates:
            raise LockError(
                "%s is a virtual package with several providers; request one of: %s"
                % (name, ", ".join(sorted(package.name for package in candidates)))
            )
        else:
            missing.append(name)
    if missing:
        raise LockError("requested packages are not in the snapshot: %s" % ", ".join(missing))


def _satisfying_candidate(universe, selected, group):
    """Prefers an alternative that is already selected, then the first unselected candidate in apt order."""
    for relation in group:
        for candidate in universe.candidates(relation):
            if selected.get(candidate.name) == candidate:
                return candidate
    for relation in group:
        for candidate in universe.candidates(relation):
            if candidate.name not in selected:
                return candidate
    return None


def resolve(universe, requested):
    """Resolve the install closure for ``requested`` packages.

    Every Essential: yes and Priority: required package is added because mkosi
    bootstraps Debian from the essential set before installing the requested
    packages. Returns ``(selected, edges)`` where ``selected`` maps package
    names to Package records and ``edges`` maps package names to the direct
    dependency names that satisfied each Depends and Pre-Depends group.
    """
    closure = _Closure()
    _select_bootstrap(universe, closure)
    _select_requested(universe, requested, closure)
    while closure.queue:
        package = closure.queue.popleft()
        for group in package.pre_depends + package.depends:
            satisfied = _satisfying_candidate(universe, closure.selected, group)
            if satisfied is None:
                raise LockError(
                    "%s %s has an unsatisfiable dependency: %s"
                    % (package.name, package.version, _format_group(group))
                )
            closure.select(satisfied, "%s %s" % (package.name, package.version))
            if satisfied.name != package.name:
                closure.edges[package.name].add(satisfied.name)
    return closure.selected, closure.edges


def cleartext_payload(inrelease):
    """Return the dash-unescaped payload of a clear-signed InRelease file."""
    lines = inrelease.decode("utf-8").split("\n")
    try:
        start = lines.index("-----BEGIN PGP SIGNED MESSAGE-----")
        body = lines.index("", start) + 1
        end = lines.index("-----BEGIN PGP SIGNATURE-----", body)
    except ValueError as error:
        raise LockError("InRelease is not a clear-signed message") from error
    payload = [line[2:] if line.startswith("- ") else line for line in lines[body:end]]
    return ("\n".join(payload) + "\n").encode("utf-8")


def release_checksums(release):
    """Return the SHA-256 entries of a Release file keyed by relative path."""
    fields = paragraphs(release.decode("utf-8"))
    if len(fields) != 1:
        raise LockError("Release must contain exactly one paragraph")
    checksums = {}
    for line in fields[0].get("SHA256", "").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 3 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]) or not parts[1].isdigit():
            raise LockError("malformed Release SHA256 entry: %s" % line)
        if parts[2] in checksums:
            raise LockError("duplicate Release SHA256 entry: %s" % parts[2])
        checksums[parts[2]] = (parts[0], int(parts[1]))
    return fields[0], checksums


@dataclasses.dataclass(frozen=True)
class Specification:
    """Validated generator input."""

    snapshot_url: str
    snapshot: str
    suite: str
    components: tuple
    packages: tuple


def _snapshot_source(data):
    """Returns the only declared source, its normalized snapshot URL, and the snapshot timestamp."""
    sources = data.get("sources")
    if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
        raise LockError("specification must declare exactly one snapshot source")
    source = sources[0]
    url = source.get("url", "")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise LockError("snapshot source url must use https")
    url = url.rstrip("/")
    snapshot = url.rsplit("/", 1)[-1]
    if not _SNAPSHOT.fullmatch(snapshot):
        raise LockError("snapshot source url must end with an immutable UTC timestamp")
    return source, url, snapshot


def _channel(source):
    """Returns the suite and components of a source channel such as ``trixie main non-free-firmware``."""
    channel = source.get("channel", "")
    words = channel.split() if isinstance(channel, str) else []
    if len(words) < 2:
        raise LockError("source channel must name a suite and at least one component")
    suite, components = words[0], words[1:]
    for name in [suite] + components:
        if not _IDENTIFIER.fullmatch(name):
            raise LockError("invalid suite or component name: %s" % name)
    if len(set(components)) != len(components):
        raise LockError("source channel repeats a component")
    if "main" not in components:
        raise LockError("source channel must include the main component")
    return suite, components


def _requested_packages(data):
    packages = data.get("packages")
    if not isinstance(packages, list) or not packages:
        raise LockError("specification must request at least one package")
    for package in packages:
        if not isinstance(package, str) or not _PACKAGE_NAME.fullmatch(package):
            raise LockError("invalid package name: %r" % (package,))
    return tuple(dict.fromkeys(packages))


def load_specification(data):
    """Validate a decoded JSON specification."""
    if not isinstance(data, dict):
        raise LockError("specification must be a JSON object")
    unknown = set(data) - {"version", "sources", "archs", "packages"}
    if unknown:
        raise LockError("unknown specification fields: %s" % ", ".join(sorted(unknown)))
    if data.get("version") != 1:
        raise LockError("specification version must be 1")
    source, url, snapshot = _snapshot_source(data)
    suite, components = _channel(source)
    if data.get("archs") != [ARCHITECTURE]:
        raise LockError("archs must be [%r]; arch: all is included implicitly" % ARCHITECTURE)
    return Specification(
        snapshot_url=url,
        snapshot=snapshot,
        suite=suite,
        components=("main",) + tuple(sorted(set(components) - {"main"})),
        packages=_requested_packages(data),
    )


def fetch(url, attempts=4):
    """Download ``url`` with bounded retries for transient snapshot failures."""
    request = urllib.request.Request(url, headers={"User-Agent": "rules_mkosi-generate-lock"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            status = getattr(error, "code", None)
            if status is not None and status < 500 and status != 429:
                raise LockError("cannot download %s: %s" % (url, error)) from error
            if attempt + 1 == attempts:
                raise LockError("cannot download %s: %s" % (url, error)) from error
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _metadata_entry(name, path, data, snapshot_url, **extra):
    entry = {
        "name": name,
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "url": snapshot_url + "/" + path,
    }
    entry.update(extra)
    return entry


def _index_name(component, architecture):
    prefix = "" if component == "main" else component + "_"
    return prefix + ("packages_xz" if architecture == ARCHITECTURE else "packages_all_xz")


def _fetch_release(url, base, fetcher):
    """Downloads InRelease, Release and Release.gpg and checks that InRelease carries the Release payload."""
    inrelease = fetcher("%s/%s/InRelease" % (url, base))
    release_data = fetcher("%s/%s/Release" % (url, base))
    release_gpg = fetcher("%s/%s/Release.gpg" % (url, base))
    payload = cleartext_payload(inrelease)
    if payload != release_data and payload != release_data + b"\n":
        raise LockError("InRelease payload does not match Release")
    return inrelease, release_data, release_gpg


def _release_number(fields, specification, release):
    """Checks that Release provides the requested suite, components and architecture; returns its number."""
    if fields.get("Codename") != specification.suite:
        raise LockError(
            "source suite %s must be the Release codename %s"
            % (specification.suite, fields.get("Codename"))
        )
    available = set(fields.get("Components", "").split())
    missing = sorted(set(specification.components) - available)
    if missing:
        raise LockError("Release does not provide components: %s" % ", ".join(missing))
    if ARCHITECTURE not in fields.get("Architectures", "").split():
        raise LockError("Release does not provide architecture %s" % ARCHITECTURE)
    release_number = release or fields.get("Version", "").split(".", 1)[0]
    if not release_number.isdigit():
        raise LockError("Release has no numeric Version; pass --release")
    return release_number


def _fetch_index(url, base, relative, checksums, fetcher):
    """Downloads one Packages.xz and verifies it against the Release SHA-256 list."""
    if relative not in checksums:
        raise LockError("Release does not list %s" % relative)
    data = fetcher("%s/%s/%s" % (url, base, relative))
    digest, size = checksums[relative]
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise LockError("%s does not match the Release checksum" % relative)
    return data


def _decode_index(relative, data):
    try:
        return lzma.decompress(data).decode("utf-8")
    except (lzma.LZMAError, UnicodeDecodeError) as error:
        raise LockError("%s cannot be decoded: %s" % (relative, error)) from error


def _fetch_indexes(specification, base, checksums, fetcher):
    """Returns the metadata entries and package records of every authenticated Packages index."""
    url = specification.snapshot_url
    metadata = []
    packages = []
    for component in specification.components:
        for architecture in INDEX_ARCHITECTURES:
            relative = "%s/binary-%s/Packages.xz" % (component, architecture)
            data = _fetch_index(url, base, relative, checksums, fetcher)
            metadata.append(
                _metadata_entry(
                    _index_name(component, architecture),
                    base + "/" + relative,
                    data,
                    url,
                    architecture=architecture,
                    component=component,
                )
            )
            packages.extend(parse_packages(_decode_index(relative, data), component, architecture))
    return metadata, packages


def _locked_package(package, dependencies, url):
    return {
        "arch": package.architecture,
        "component": package.component,
        "dependencies": [
            {"key": dependency.key, "name": dependency.name, "version": dependency.version}
            for dependency in sorted(dependencies, key=lambda dependency: dependency.key)
        ],
        "filename": package.filename,
        "key": package.key,
        "name": package.name,
        "sha256": package.sha256,
        "size": package.size,
        "urls": [url + "/" + package.filename],
        "version": package.version,
    }


def _locked_packages(selected, edges, url):
    locked = [
        _locked_package(selected[name], (selected[dependency] for dependency in edges[name]), url)
        for name in sorted(selected, key=lambda item: selected[item].key)
    ]
    keys = [package["key"] for package in locked]
    if len(set(keys)) != len(keys):
        raise LockError("resolved packages have colliding lock keys")
    return locked


def generate(specification, fetcher=fetch, release=None):
    """Return the lock dictionary for a validated specification.

    ``fetcher`` maps an absolute URL to its bytes, which keeps tests offline.
    ``release`` optionally overrides the numeric Debian release when the
    snapshot's Release file has no Version field.
    """
    base = "dists/%s" % specification.suite
    url = specification.snapshot_url
    inrelease, release_data, release_gpg = _fetch_release(url, base, fetcher)
    fields, checksums = release_checksums(release_data)
    release_number = _release_number(fields, specification, release)
    metadata = [
        _metadata_entry("inrelease", base + "/InRelease", inrelease, url),
        _metadata_entry("release", base + "/Release", release_data, url),
        _metadata_entry("release_gpg", base + "/Release.gpg", release_gpg, url),
    ]
    index_metadata, packages = _fetch_indexes(specification, base, checksums, fetcher)
    selected, edges = resolve(Universe(packages), specification.packages)
    return {
        "packages": _locked_packages(selected, edges, url),
        "repository": {
            "architecture": ARCHITECTURE,
            "codename": specification.suite,
            "components": list(specification.components),
            "distribution": "debian",
            "metadata": metadata + index_metadata,
            "release": release_number,
            "snapshot": specification.snapshot,
            "snapshot_url": url,
        },
        "version": 1,
    }


def render(lock):
    """Serialize a lock deterministically."""
    return json.dumps(lock, indent=2, sort_keys=True) + "\n"


def _workspace_path(path):
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    path = pathlib.Path(path)
    if workspace and not path.is_absolute():
        return pathlib.Path(workspace) / path
    return path


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--spec", required=True, help="JSON package specification")
    parser.add_argument("--output", required=True, help="lock file to write or check")
    parser.add_argument(
        "--release",
        help="numeric Debian release, required only when Release has no Version field",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing when the output lock is out of date",
    )
    return parser


def _render_lock(spec_path, release):
    try:
        data = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LockError("specification is not valid JSON: %s" % error) from error
    return render(generate(load_specification(data), release=release))


def main(argv=None):
    args = _parser().parse_args(argv)
    spec_path = _workspace_path(args.spec)
    output = _workspace_path(args.output)
    try:
        lock = _render_lock(spec_path, args.release)
    except (LockError, OSError) as error:
        print("Debian lock generation failed: %s" % error, file=sys.stderr)
        return 1
    if args.check:
        current = output.read_text(encoding="utf-8") if output.is_file() else None
        if current != lock:
            print("%s is out of date; regenerate it without --check" % args.output, file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(lock, encoding="utf-8")
    print("wrote %s with %d packages" % (args.output, len(json.loads(lock)["packages"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
