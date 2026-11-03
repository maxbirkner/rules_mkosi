"""Hermetic tests for the Debian snapshot lock generator."""

import hashlib
import json
import lzma
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import generate_lock  # noqa: E402

_SNAPSHOT_URL = "https://snapshot.debian.org/archive/debian/20250814T000000Z"


def _stanza(name, version="1", architecture="amd64", component="main", **fields):
    lines = [
        "Package: %s" % name,
        "Version: %s" % version,
        "Architecture: %s" % architecture,
    ]
    for field, value in fields.items():
        lines.append("%s: %s" % (field.replace("_", "-"), value))
    filename = "pool/%s/%s/%s/%s_%s_%s.deb" % (
        component,
        name[0],
        name,
        name,
        version.split(":")[-1],
        architecture,
    )
    lines += [
        "Filename: %s" % filename,
        "Size: %d" % len(name),
        "SHA256: %s" % hashlib.sha256(name.encode()).hexdigest(),
    ]
    return "\n".join(lines) + "\n"


def _universe(*stanzas, component="main"):
    packages = []
    for stanza in stanzas:
        packages.extend(generate_lock.parse_packages(stanza, component, "amd64"))
    return generate_lock.Universe(packages)


def _names(universe, requested):
    selected, _ = generate_lock.resolve(universe, requested)
    return sorted(selected)


class VersionTest(unittest.TestCase):
    def test_dpkg_ordering(self):
        ordered = [
            "1.0~rc1",
            "1.0",
            "1.0-1",
            "1.0-1+b1",
            "1.0a",
            "1.1",
            "1.10",
            "1:0.1",
        ]
        for left, right in zip(ordered, ordered[1:]):
            self.assertLess(generate_lock.compare_versions(left, right), 0, (left, right))
            self.assertGreater(generate_lock.compare_versions(right, left), 0, (left, right))
        self.assertEqual(0, generate_lock.compare_versions("0:1.0-1", "1.0-1"))
        self.assertEqual(0, generate_lock.compare_versions("1.01", "1.1"))

    def test_relations(self):
        self.assertTrue(generate_lock.version_satisfies("2.0", ">=", "2.0"))
        self.assertTrue(generate_lock.version_satisfies("2.0", ">>", "1.9"))
        self.assertFalse(generate_lock.version_satisfies("2.0", "<<", "2.0"))
        self.assertTrue(generate_lock.version_satisfies("2.0", "<=", "2.0"))
        self.assertTrue(generate_lock.version_satisfies("1:1.0", "=", "1:1.0"))


class RelationParsingTest(unittest.TestCase):
    def test_alternatives_qualifiers_and_versions(self):
        groups = generate_lock.parse_relations(
            "libc6 (>= 2.36), perl:any, foo | bar (<< 3~),\n baz [amd64] <!nocheck>"
        )
        self.assertEqual(4, len(groups))
        self.assertEqual(generate_lock.Relation("libc6", None, ">=", "2.36"), groups[0][0])
        self.assertEqual("any", groups[1][0].arch)
        self.assertEqual(["foo", "bar"], [relation.name for relation in groups[2]])
        self.assertEqual(("<<", "3~"), (groups[2][1].operator, groups[2][1].version))
        self.assertEqual("baz", groups[3][0].name)

    def test_malformed_relation_is_rejected(self):
        with self.assertRaisesRegex(generate_lock.LockError, "malformed"):
            generate_lock.parse_relations("Bad Name")


class ResolverTest(unittest.TestCase):
    def test_bootstrap_set_is_included_and_recommends_are_ignored(self):
        universe = _universe(
            _stanza("base-files", Essential="yes", Priority="required"),
            _stanza("login", Priority="required"),
            _stanza("optional-tool", Priority="optional"),
            _stanza("app", Recommends="optional-tool", Suggests="other"),
        )
        self.assertEqual(["app", "base-files", "login"], _names(universe, ["app"]))

    def test_depends_and_pre_depends_closure(self):
        universe = _universe(
            _stanza("app", Pre_Depends="pre", Depends="lib"),
            _stanza("pre", Depends="deep"),
            _stanza("lib"),
            _stanza("deep"),
        )
        selected, edges = generate_lock.resolve(universe, ["app"])
        self.assertEqual(["app", "deep", "lib", "pre"], sorted(selected))
        self.assertEqual({"lib", "pre"}, edges["app"])

    def test_first_satisfiable_alternative_is_selected(self):
        universe = _universe(
            _stanza("app", Depends="missing | second | third"),
            _stanza("second"),
            _stanza("third"),
        )
        self.assertEqual(["app", "second"], _names(universe, ["app"]))

    def test_already_selected_alternative_is_preferred(self):
        universe = _universe(
            _stanza("app", Depends="first | second, needs-second"),
            _stanza("needs-second", Depends="second"),
            _stanza("first"),
            _stanza("second"),
        )
        self.assertEqual(
            ["app", "first", "needs-second", "second"], _names(universe, ["app"])
        )
        universe = _universe(
            _stanza("base", Essential="yes", Depends="second"),
            _stanza("app", Depends="first | second"),
            _stanza("first"),
            _stanza("second"),
        )
        self.assertEqual(["app", "base", "second"], _names(universe, ["app"]))

    def test_version_constraints_select_a_satisfying_candidate(self):
        universe = _universe(
            _stanza("app", Depends="lib (>= 2)"),
            _stanza("lib", version="1"),
            _stanza("lib", version="2"),
            _stanza("lib", version="3~beta"),
        )
        selected, _ = generate_lock.resolve(universe, ["app"])
        self.assertEqual("3~beta", selected["lib"].version)
        universe = _universe(
            _stanza("app", Depends="lib (<< 2)"),
            _stanza("lib", version="1"),
            _stanza("lib", version="2"),
        )
        selected, _ = generate_lock.resolve(universe, ["app"])
        self.assertEqual("1", selected["lib"].version)

    def test_unsatisfiable_version_constraint_is_reported(self):
        universe = _universe(
            _stanza("app", Depends="lib (>= 2)"),
            _stanza("lib", version="1"),
        )
        with self.assertRaisesRegex(generate_lock.LockError, r"app 1 .*lib \(>= 2\)"):
            generate_lock.resolve(universe, ["app"])

    def test_conflicting_versions_of_one_package_are_rejected(self):
        universe = _universe(
            _stanza("base", Essential="yes", Depends="lib (= 1)"),
            _stanza("app", Depends="lib (= 2)"),
            _stanza("lib", version="1"),
            _stanza("lib", version="2"),
        )
        with self.assertRaisesRegex(generate_lock.LockError, "unsatisfiable"):
            generate_lock.resolve(universe, ["app"])

    def test_virtual_packages_and_versioned_provides(self):
        universe = _universe(
            _stanza("app", Depends="mail-transport-agent, abi (>= 2)"),
            _stanza("zz-mta", Provides="mail-transport-agent", Priority="optional"),
            _stanza("aa-mta", Provides="mail-transport-agent", Priority="extra"),
            _stanza("old-abi", Provides="abi (= 1)"),
            _stanza("new-abi", Provides="abi (= 2)"),
            _stanza("unversioned-abi", Provides="abi"),
        )
        self.assertEqual(["app", "new-abi", "zz-mta"], _names(universe, ["app"]))

    def test_architecture_qualifiers_follow_multi_arch(self):
        universe = _universe(
            _stanza("app", Depends="perl:any, tool:amd64"),
            _stanza("perl", Multi_Arch="allowed"),
            _stanza("tool"),
        )
        self.assertEqual(["app", "perl", "tool"], _names(universe, ["app"]))
        universe = _universe(
            _stanza("app", Depends="helper:i386"),
            _stanza("helper", Multi_Arch="foreign"),
        )
        self.assertEqual(["app", "helper"], _names(universe, ["app"]))
        universe = _universe(
            _stanza("app", Depends="library:i386"),
            _stanza("library", Multi_Arch="same"),
        )
        with self.assertRaisesRegex(generate_lock.LockError, "library:i386"):
            generate_lock.resolve(universe, ["app"])

    def test_architecture_all_packages_satisfy_native_relations(self):
        universe = generate_lock.Universe(
            generate_lock.parse_packages(_stanza("app", Depends="data"), "main", "amd64")
            + generate_lock.parse_packages(
                _stanza("data", architecture="all"), "main", "all"
            )
        )
        selected, _ = generate_lock.resolve(universe, ["app"])
        self.assertEqual("all", selected["data"].architecture)

    def test_missing_and_ambiguous_requests_are_rejected(self):
        universe = _universe(
            _stanza("one", Provides="virtual"),
            _stanza("two", Provides="virtual"),
            _stanza("three", Provides="unique"),
        )
        with self.assertRaisesRegex(generate_lock.LockError, "not in the snapshot: absent"):
            generate_lock.resolve(universe, ["absent"])
        with self.assertRaisesRegex(generate_lock.LockError, "several providers"):
            generate_lock.resolve(universe, ["virtual"])
        self.assertEqual(["three"], _names(universe, ["unique"]))

    def test_packages_from_other_components_are_resolved(self):
        packages = generate_lock.parse_packages(_stanza("app", Depends="firmware"), "main", "amd64")
        packages += generate_lock.parse_packages(
            _stanza("firmware", component="non-free-firmware"),
            "non-free-firmware",
            "amd64",
        )
        selected, _ = generate_lock.resolve(generate_lock.Universe(packages), ["app"])
        self.assertEqual("non-free-firmware", selected["firmware"].component)

    def test_packages_index_continuation_lines_extend_relations(self):
        index = _stanza("app", Description="app\n Long description.\n .\n More.") + "Depends: base,\n  data (>= 1)\n"
        (package,) = generate_lock.parse_packages(index, "main", "amd64")
        self.assertEqual(
            (
                (generate_lock.Relation("base"),),
                (generate_lock.Relation("data", None, ">=", "1"),),
            ),
            package.depends,
        )

    def test_malformed_control_data_is_a_lock_error(self):
        with self.assertRaisesRegex(generate_lock.LockError, "^duplicate Debian metadata field: Package$"):
            generate_lock.paragraphs("Package: one\nPackage: two\n")

    def test_binary_all_index_rejects_native_packages(self):
        with self.assertRaisesRegex(generate_lock.LockError, "non-all"):
            generate_lock.parse_packages(_stanza("app"), "main", "all")


class SpecificationTest(unittest.TestCase):
    def _specification(self, **overrides):
        data = {
            "version": 1,
            "sources": [
                {"channel": "trixie non-free-firmware main", "url": _SNAPSHOT_URL + "/"}
            ],
            "archs": ["amd64"],
            "packages": ["bb", "aa", "bb"],
        }
        data.update(overrides)
        return data

    def test_normalizes_components_and_packages(self):
        specification = generate_lock.load_specification(self._specification())
        self.assertEqual(("main", "non-free-firmware"), specification.components)
        self.assertEqual(("bb", "aa"), specification.packages)
        self.assertEqual("20250814T000000Z", specification.snapshot)
        self.assertEqual(_SNAPSHOT_URL, specification.snapshot_url)

    def test_rejects_unpinned_or_incomplete_specifications(self):
        for overrides, message in (
            ({"sources": [{"channel": "trixie main", "url": "https://deb.debian.org/debian"}]}, "timestamp"),
            ({"sources": [{"channel": "trixie contrib", "url": _SNAPSHOT_URL}]}, "main"),
            ({"sources": [{"channel": "trixie", "url": _SNAPSHOT_URL}]}, "component"),
            ({"archs": ["arm64"]}, "archs"),
            ({"packages": []}, "at least one"),
            ({"packages": ["Bad"]}, "invalid package"),
            ({"version": 2}, "version"),
            ({"mirror": "x"}, "unknown"),
        ):
            with self.assertRaisesRegex(generate_lock.LockError, message):
                generate_lock.load_specification(self._specification(**overrides))


class GenerateTest(unittest.TestCase):
    def setUp(self):
        base = _SNAPSHOT_URL + "/dists/trixie/"
        self.indexes = {
            "main/binary-amd64/Packages.xz": lzma.compress(
                (
                    _stanza("base-files", Essential="yes")
                    + "\n"
                    + _stanza("libc6", version="2.41-12", Depends="data")
                ).encode()
            ),
            "main/binary-all/Packages.xz": lzma.compress(
                _stanza("data", architecture="all").encode()
            ),
            "non-free-firmware/binary-amd64/Packages.xz": lzma.compress(
                _stanza(
                    "amd64-microcode",
                    version="3.20250311.1",
                    component="non-free-firmware",
                    Depends="libc6 (>= 2.36)",
                ).encode()
            ),
            "non-free-firmware/binary-all/Packages.xz": lzma.compress(b""),
        }
        checksums = "".join(
            " %s %d %s\n" % (hashlib.sha256(data).hexdigest(), len(data), path)
            for path, data in sorted(self.indexes.items())
        )
        self.release = (
            "Codename: trixie\nVersion: 13.0\n"
            "Architectures: all amd64\nComponents: main contrib non-free-firmware\n"
            "SHA256:\n" + checksums
        ).encode()
        inrelease = (
            b"-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\n"
            + self.release
            + b"-----BEGIN PGP SIGNATURE-----\nsignature\n-----END PGP SIGNATURE-----\n"
        )
        self.files = {
            base + "InRelease": inrelease,
            base + "Release": self.release,
            base + "Release.gpg": b"detached signature",
        }
        for path, data in self.indexes.items():
            self.files[base + path] = data
        self.specification = generate_lock.load_specification(
            {
                "version": 1,
                "sources": [
                    {"channel": "trixie main non-free-firmware", "url": _SNAPSHOT_URL}
                ],
                "archs": ["amd64"],
                "packages": ["amd64-microcode"],
            }
        )

    def test_generates_deterministic_multi_component_lock(self):
        lock = generate_lock.generate(self.specification, fetcher=self.files.__getitem__)
        rendered = generate_lock.render(lock)
        self.assertEqual(rendered, generate_lock.render(json.loads(rendered)))
        repository = lock["repository"]
        self.assertEqual(["main", "non-free-firmware"], repository["components"])
        self.assertEqual("13", repository["release"])
        self.assertEqual(
            [
                "inrelease",
                "release",
                "release_gpg",
                "packages_xz",
                "packages_all_xz",
                "non-free-firmware_packages_xz",
                "non-free-firmware_packages_all_xz",
            ],
            [entry["name"] for entry in repository["metadata"]],
        )
        packages = {package["name"]: package for package in lock["packages"]}
        self.assertEqual(["amd64-microcode", "base-files", "data", "libc6"], sorted(packages))
        firmware = packages["amd64-microcode"]
        self.assertEqual("non-free-firmware", firmware["component"])
        self.assertEqual([_SNAPSHOT_URL + "/" + firmware["filename"]], firmware["urls"])
        self.assertEqual(["libc6"], [entry["name"] for entry in firmware["dependencies"]])
        self.assertEqual("libc6_2.41-12_amd64", packages["libc6"]["key"])
        self.assertEqual(
            [package["key"] for package in lock["packages"]],
            sorted(package["key"] for package in lock["packages"]),
        )

    def test_index_must_match_release_checksum(self):
        path = _SNAPSHOT_URL + "/dists/trixie/non-free-firmware/binary-amd64/Packages.xz"
        self.files[path] = lzma.compress(b"")
        with self.assertRaisesRegex(generate_lock.LockError, "Release checksum"):
            generate_lock.generate(self.specification, fetcher=self.files.__getitem__)

    def test_inrelease_must_carry_the_release_payload(self):
        self.files[_SNAPSHOT_URL + "/dists/trixie/Release"] = self.release + b"Extra: field\n"
        with self.assertRaisesRegex(generate_lock.LockError, "InRelease payload"):
            generate_lock.generate(self.specification, fetcher=self.files.__getitem__)

    def test_component_must_be_published(self):
        specification = generate_lock.load_specification(
            {
                "version": 1,
                "sources": [{"channel": "trixie main non-free", "url": _SNAPSHOT_URL}],
                "archs": ["amd64"],
                "packages": ["libc6"],
            }
        )
        with self.assertRaisesRegex(generate_lock.LockError, "components: non-free"):
            generate_lock.generate(specification, fetcher=self.files.__getitem__)


if __name__ == "__main__":
    unittest.main()
