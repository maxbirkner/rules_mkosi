"""Tests for the shared Debian control-file (deb822) parser."""

import importlib.util
import pathlib
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "debian_control", pathlib.Path(__file__).resolve().parent.parent / "private/debian_control.py"
)
debian_control = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(debian_control)

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64


class DebianControlTest(unittest.TestCase):
    def test_release_sha256_continuation_lines_become_one_stripped_entry_per_line(self):
        release = (
            "Origin: Debian\n"
            "Codename: trixie\n"
            "SHA256:\n"
            " %s 1234 main/binary-amd64/Packages.xz\n"
            "\t%s   99 main/binary-all/Packages.xz  \n" % (_DIGEST_A, _DIGEST_B)
        )
        self.assertEqual(
            [
                {
                    "Origin": "Debian",
                    "Codename": "trixie",
                    "SHA256": "\n%s 1234 main/binary-amd64/Packages.xz\n%s   99 main/binary-all/Packages.xz"
                    % (_DIGEST_A, _DIGEST_B),
                }
            ],
            debian_control.paragraphs(release),
        )

    def test_packages_index_continuation_lines_extend_folded_and_multiline_fields(self):
        packages = (
            "Package: demo\n"
            "Version: 1.0-1\n"
            "Depends: libc6 (>= 2.36),\n"
            "  zlib1g\n"
            "Description: demo package\n"
            " First line.\n"
            " .\n"
            " Last line.\n"
            "SHA256: %s\n"
            "\n"
            "Package: other\n"
            "Version: 2\n" % _DIGEST_A
        )
        self.assertEqual(
            [
                {
                    "Package": "demo",
                    "Version": "1.0-1",
                    "Depends": "libc6 (>= 2.36),\nzlib1g",
                    "Description": "demo package\nFirst line.\n.\nLast line.",
                    "SHA256": _DIGEST_A,
                },
                {"Package": "other", "Version": "2"},
            ],
            debian_control.paragraphs(packages),
        )

    def test_values_lose_surrounding_whitespace_and_keep_inner_colons(self):
        self.assertEqual(
            [{"Filename": "pool/main/d/demo.deb", "Homepage": "https://example.org:8080/x", "Size": "3"}],
            debian_control.paragraphs(
                "Filename:pool/main/d/demo.deb\nHomepage: https://example.org:8080/x\nSize: \t3 \t\n"
            ),
        )

    def test_whitespace_only_lines_separate_paragraphs(self):
        self.assertEqual(
            [{"Package": "one"}, {"Package": "two"}],
            debian_control.paragraphs("\n \nPackage: one\n \t\n\nPackage: two\n\n"),
        )

    def test_empty_text_has_no_paragraphs(self):
        self.assertEqual([], debian_control.paragraphs(""))

    def test_malformed_control_data_is_rejected(self):
        for text, message in (
            (" continued\n", "continuation without a Debian metadata field"),
            ("Package: one\n\n continued\n", "continuation without a Debian metadata field"),
            ("Package: one\nno colon\n", "malformed Debian metadata field: no colon"),
            ("Package: one\nPackage: two\n", "duplicate Debian metadata field: Package"),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "^%s$" % message):
                debian_control.paragraphs(text)


if __name__ == "__main__":
    unittest.main()
