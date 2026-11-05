"""Tests the retries and back-off of http_download."""

import email.message
import io
import pathlib
import sys
import unittest
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import http_download

URL = "https://snapshot.example/archive/debian/InRelease"


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(URL, code, "status {}".format(code), headers, None)


class _Server:
    """Answers each request with the next outcome: an exception to raise, or a response body."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.delays = []

    def open(self, request, timeout):
        self.requests.append((request.full_url, request.get_header("User-agent"), timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(outcome)

    def download(self, attempts=8):
        return http_download.download(URL, "agent", 30, attempts=attempts, opener=self.open, sleep=self.delays.append)


class DownloadTest(unittest.TestCase):
    def test_returns_the_body_without_retrying(self):
        server = _Server(b"payload")
        self.assertEqual(b"payload", server.download())
        self.assertEqual([(URL, "agent", 30)], server.requests)
        self.assertEqual([], server.delays)

    def test_retries_throttling_and_server_errors_with_exponential_back_off(self):
        server = _Server(http_error(429), http_error(503), http_error(504), b"payload")
        self.assertEqual(b"payload", server.download())
        self.assertEqual([1, 2, 4], server.delays)

    def test_retries_connection_failures(self):
        failures = (urllib.error.URLError("reset"), TimeoutError("slow"), ConnectionResetError("reset"))
        server = _Server(*failures, b"payload")
        self.assertEqual(b"payload", server.download())
        self.assertEqual(3, len(server.delays))

    def test_waits_for_the_servers_retry_after_up_to_a_minute(self):
        server = _Server(http_error(503, "7"), http_error(503, "600"), http_error(503, "soon"), b"payload")
        self.assertEqual(b"payload", server.download())
        self.assertEqual([7, http_download.MAX_DELAY_SECONDS, 4], server.delays)

    def test_permanent_errors_are_not_retried(self):
        server = _Server(http_error(404))
        with self.assertRaisesRegex(http_download.DownloadError, "cannot download .*InRelease: HTTP Error 404"):
            server.download()
        self.assertEqual([], server.delays)

    def test_gives_up_after_the_last_attempt(self):
        server = _Server(*(http_error(503) for _ in range(3)))
        with self.assertRaisesRegex(http_download.DownloadError, "HTTP Error 503"):
            server.download(attempts=3)
        self.assertEqual([1, 2], server.delays)


if __name__ == "__main__":
    unittest.main()
