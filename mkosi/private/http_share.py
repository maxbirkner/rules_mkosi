#!/usr/bin/python3
"""Answers one HTTP request on standard input and output with a file below a directory.

QEMU's user network starts it for each guest connection to the address of a guestfwd rule, with the connection as
standard input, output and error. Diagnostics therefore go to a log file instead of standard error.
"""

import http.server
import os
import sys


class _ConnectionHandler(http.server.SimpleHTTPRequestHandler):
    """Serves GET and HEAD requests over the inherited connection."""

    def setup(self):
        self.rfile = sys.stdin.buffer
        self.wfile = sys.stdout.buffer

    def finish(self):
        self.wfile.flush()

    def log_message(self, format, *args):
        print(format % args, file=sys.stderr, flush=True)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: http_share.py DIRECTORY LOG")
    os.dup2(os.open(sys.argv[2], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644), 2)
    _ConnectionHandler(None, ("guest", 0), None, directory=sys.argv[1])


if __name__ == "__main__":
    main()
