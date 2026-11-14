"""Tests http_share.py, the server of qemu_ovmf_boot_test http_shares, through its standard input and output."""

import base64
import hashlib
import http.client
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest

_SERVER = pathlib.Path(__file__).parents[1] / "private" / "http_share.py"
_CONTENT = bytes(range(256)) * 300
_DIGEST = "sha-256=:{}:".format(base64.b64encode(hashlib.sha256(_CONTENT).digest()).decode())


class HttpShareTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        (self.root / "share" / "nested").mkdir(parents=True)
        (self.root / "share" / "root.raw").write_bytes(_CONTENT)
        (self.root / "share" / "empty").write_bytes(b"")

    def _request(self, method, path, **headers):
        """Sends one request to a fresh server process and returns its status, headers, and body."""
        lines = ["{} {} HTTP/1.1".format(method, path), "Host: 10.0.2.100"]
        lines += ["{}: {}".format(name.replace("_", "-"), value) for name, value in headers.items()]
        request = ("\r\n".join(lines) + "\r\n\r\n").encode()
        response = subprocess.run(
            [sys.executable, "-I", str(_SERVER), str(self.root / "share"), str(self.root / "http-share.log")],
            input=request,
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout
        stream = io.BytesIO(response)
        status = int(stream.readline().split()[1])
        return status, http.client.parse_headers(stream), stream.read()

    def test_get_and_head_carry_the_digest_of_the_whole_file(self):
        for method, body in (("GET", _CONTENT), ("HEAD", b"")):
            with self.subTest(method=method):
                status, headers, received = self._request(method, "/root.raw")
                self.assertEqual(200, status)
                self.assertEqual(_DIGEST, headers["Content-Digest"])
                self.assertEqual(str(len(_CONTENT)), headers["Content-Length"])
                self.assertEqual("bytes", headers["Accept-Ranges"])
                self.assertIn("Last-Modified", headers)
                self.assertIn("Content-type", headers)
                self.assertIsNone(headers["Content-Range"])
                self.assertEqual(body, received)

    def test_empty_file_has_the_digest_of_no_bytes(self):
        status, headers, body = self._request("GET", "/empty")
        self.assertEqual((200, b""), (status, body))
        self.assertEqual("sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:", headers["Content-Digest"])

    def test_single_ranges_return_partial_content(self):
        size = len(_CONTENT)
        cases = {
            "bytes=10-19": (10, 19),
            "bytes=100-": (100, size - 1),
            "bytes=-25": (size - 25, size - 1),
            "bytes=-{}".format(size + 10): (0, size - 1),
            "bytes={}-{}".format(size - 5, size + 100): (size - 5, size - 1),
            "BYTES=0-0": (0, 0),
        }
        for header, (first, last) in cases.items():
            for method, body in (("GET", _CONTENT[first : last + 1]), ("HEAD", b"")):
                with self.subTest(range=header, method=method):
                    status, headers, received = self._request(method, "/root.raw", Range=header)
                    self.assertEqual(206, status)
                    self.assertEqual("bytes {}-{}/{}".format(first, last, size), headers["Content-Range"])
                    self.assertEqual(str(last - first + 1), headers["Content-Length"])
                    self.assertEqual(_DIGEST, headers["Content-Digest"])
                    self.assertEqual(body, received)

    def test_unsatisfiable_ranges_return_416_with_the_size(self):
        size = len(_CONTENT)
        for path, header, length in (
            ("/root.raw", "bytes={}-".format(size), size),
            ("/root.raw", "bytes={}-{}".format(size + 1, size + 9), size),
            ("/root.raw", "bytes=-0", size),
            ("/empty", "bytes=0-", 0),
            ("/empty", "bytes=-1", 0),
        ):
            with self.subTest(path=path, range=header):
                status, headers, body = self._request("GET", path, Range=header)
                self.assertEqual(416, status)
                self.assertEqual("bytes */{}".format(length), headers["Content-Range"])
                self.assertIsNone(headers["Content-Digest"])
                self.assertEqual(b"", body)

    def test_multiple_and_malformed_ranges_return_the_whole_file(self):
        for header in (
            "bytes=0-1,5-6",
            "bytes=9-3",
            "bytes=-",
            "bytes=a-b",
            "lines=0-1",
            "bytes={}-".format("9" * 5000),
        ):
            with self.subTest(range=header):
                status, headers, body = self._request("GET", "/root.raw", Range=header)
                self.assertEqual(200, status)
                self.assertEqual(_DIGEST, headers["Content-Digest"])
                self.assertIsNone(headers["Content-Range"])
                self.assertEqual(_CONTENT, body)

    def test_if_range_honors_the_range_only_for_the_current_last_modified(self):
        _, headers, _ = self._request("HEAD", "/root.raw")
        status, _, body = self._request("GET", "/root.raw", Range="bytes=0-3", If_Range=headers["Last-Modified"])
        self.assertEqual((206, _CONTENT[:4]), (status, body))
        stale = "Thu, 01 Jan 1970 00:00:00 GMT"
        status, _, body = self._request("GET", "/root.raw", Range="bytes=0-3", If_Range=stale)
        self.assertEqual((200, _CONTENT), (status, body))

    def test_if_modified_since_returns_not_modified(self):
        _, headers, _ = self._request("HEAD", "/root.raw")
        status, headers, body = self._request("GET", "/root.raw", If_Modified_Since=headers["Last-Modified"])
        self.assertEqual((304, b""), (status, body))
        self.assertIsNone(headers["Content-Digest"])

    def test_missing_files_return_404_without_a_digest(self):
        for path in ("/missing", "/root.raw/", "/nested/missing"):
            with self.subTest(path=path):
                status, headers, _ = self._request("GET", path)
                self.assertEqual(404, status)
                self.assertIsNone(headers["Content-Digest"])

    def test_directories_are_listed_and_requests_logged(self):
        status, headers, body = self._request("GET", "/")
        self.assertEqual(200, status)
        self.assertIsNone(headers["Content-Digest"])
        self.assertIn(b'href="root.raw"', body)
        self.assertEqual(301, self._request("GET", "/nested")[0])
        self._request("GET", "/root.raw", Range="bytes=0-0")
        log = (self.root / "http-share.log").read_text()
        self.assertIn('"GET / HTTP/1.1" 200', log)
        self.assertIn('"GET /root.raw HTTP/1.1" 206', log)


if __name__ == "__main__":
    unittest.main()
