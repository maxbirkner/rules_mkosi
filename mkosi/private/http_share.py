#!/usr/bin/python3
"""Answers one HTTP request on standard input and output with a file below a directory.

QEMU's user network starts it for each guest connection to the address of a guestfwd rule, with the connection as
standard input, output and error. Diagnostics therefore go to a log file instead of standard error.

Responses for regular files carry an RFC 9530 Content-Digest with the SHA-256 of the whole file, also when a single
byte range of it is requested, and answer such a request with 206 Partial Content. Requests for several ranges get the
whole file.
"""

import base64
import datetime
import email.utils
import hashlib
import http.server
import os
import re
import sys
from http import HTTPStatus

_CHUNK = 1 << 20
# Longer positions are malformed: they exceed any file, and Python refuses to convert integers of over 4300 digits.
_SINGLE_RANGE = re.compile(r"bytes=(\d{0,19})-(\d{0,19})", re.IGNORECASE)


class _UnsatisfiableRange(Exception):
    pass


def _content_digest(file):
    """Returns the Content-Digest value of an open file by reading it, and rewinds the file."""
    digest = hashlib.sha256()
    while chunk := file.read(_CHUNK):
        digest.update(chunk)
    file.seek(0)
    return "sha-256=:{}:".format(base64.b64encode(digest.digest()).decode())


def _byte_range(header, size):
    """Returns the inclusive (first, last) positions of a single-range Range header, or None for the whole file.

    Raises _UnsatisfiableRange when the range selects no byte of the file. Malformed headers and headers with several
    ranges select the whole file, which RFC 9110 permits.
    """
    match = _SINGLE_RANGE.fullmatch(header.strip()) if header else None
    if not match or match.groups() == ("", ""):
        return None
    first, last = match.groups()
    if not first:
        if int(last) == 0 or size == 0:
            raise _UnsatisfiableRange
        return max(size - int(last), 0), size - 1
    if last and int(last) < int(first):
        return None
    if int(first) >= size:
        raise _UnsatisfiableRange
    return int(first), min(int(last), size - 1) if last else size - 1


class _ConnectionHandler(http.server.SimpleHTTPRequestHandler):
    """Serves GET and HEAD requests over the inherited connection."""

    # Bytes of the open file that copyfile sends, or None for a directory listing.
    _remaining = None

    def setup(self):
        self.rfile = sys.stdin.buffer
        self.wfile = sys.stdout.buffer

    def finish(self):
        self.wfile.flush()

    def log_message(self, format, *args):
        print(format % args, file=sys.stderr, flush=True)

    def send_head(self):
        path = self.translate_path(self.path)
        # The base class redirects, lists directories, and rejects missing files and paths with a trailing slash.
        if not os.path.isfile(path):
            return super().send_head()
        try:
            file = open(path, "rb")  # noqa: SIM115 - do_GET and do_HEAD close it.
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None
        try:
            return self._send_file_head(path, file)
        except BaseException:
            file.close()
            raise

    def _send_file_head(self, path, file):
        """Sends the headers for an open regular file and returns it positioned at the first byte to send, or None."""
        status = os.fstat(file.fileno())
        last_modified = self.date_time_string(status.st_mtime)
        if self._not_modified(status.st_mtime):
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.end_headers()
            file.close()
            return None
        try:
            span = _byte_range(self._range_header(last_modified), status.st_size)
        except _UnsatisfiableRange:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", "bytes */{}".format(status.st_size))
            self.send_header("Content-Length", "0")
            self.end_headers()
            file.close()
            return None
        digest = _content_digest(file)
        if span is None:
            first, last = 0, status.st_size - 1
            self.send_response(HTTPStatus.OK)
        else:
            first, last = span
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", "bytes {}-{}/{}".format(first, last, status.st_size))
        self.send_header("Content-type", self.guess_type(path))
        self.send_header("Content-Length", str(last - first + 1))
        self.send_header("Last-Modified", last_modified)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Digest", digest)
        self.end_headers()
        file.seek(first)
        self._remaining = last - first + 1
        return file

    def _not_modified(self, mtime):
        """Returns whether If-Modified-Since, without If-None-Match, is not older than the modification time."""
        header = self.headers.get("If-Modified-Since")
        if header is None or "If-None-Match" in self.headers:
            return False
        try:
            since = email.utils.parsedate_to_datetime(header)
        except (TypeError, IndexError, OverflowError, ValueError):
            return False
        if since.tzinfo is None:
            since = since.replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.fromtimestamp(int(mtime), datetime.timezone.utc) <= since

    def _range_header(self, last_modified):
        """Returns the Range header, unless an If-Range precondition names another Last-Modified date."""
        condition = self.headers.get("If-Range")
        if condition is not None and condition.strip() != last_modified:
            return None
        return self.headers.get("Range")

    def copyfile(self, source, outputfile):
        if self._remaining is None:
            super().copyfile(source, outputfile)
            return
        while self._remaining > 0:
            chunk = source.read(min(self._remaining, _CHUNK))
            if not chunk:
                break
            outputfile.write(chunk)
            self._remaining -= len(chunk)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: http_share.py DIRECTORY LOG")
    os.dup2(os.open(sys.argv[2], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644), 2)
    _ConnectionHandler(None, ("guest", 0), None, directory=sys.argv[1])


if __name__ == "__main__":
    main()
