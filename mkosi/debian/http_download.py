"""Downloads a URL and retries with back-off while the server throttles or fails transiently."""

import http.client
import sys
import time
import urllib.error
import urllib.request

MAX_DELAY_SECONDS = 60
_ERRORS = (urllib.error.URLError, http.client.IncompleteRead, TimeoutError, ConnectionError)


class DownloadError(Exception):
    """A download failed with a permanent error, or every attempt failed."""


def is_transient(error):
    """Returns whether a failed download may succeed later: HTTP 429 and 5xx, timeouts, and connection failures."""
    status = getattr(error, "code", None)
    return status is None or status == 429 or status >= 500


def retry_delay(error, attempt):
    """Returns the seconds to wait after a failed attempt: the server's numeric Retry-After, or 2**attempt."""
    headers = getattr(error, "headers", None)
    retry_after = headers.get("Retry-After", "") if headers is not None else ""
    delay = int(retry_after) if retry_after.isdigit() else 2**attempt
    return min(delay, MAX_DELAY_SECONDS)


def download(url, user_agent, timeout, attempts=8, opener=urllib.request.urlopen, sleep=time.sleep):
    """Returns the body of url.

    Transient failures are retried up to attempts times in total; a permanent failure, such as HTTP 404, or the last
    failed attempt raises DownloadError.
    """
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    for attempt in range(attempts):
        try:
            with opener(request, timeout=timeout) as response:
                return response.read()
        except _ERRORS as error:
            if not is_transient(error) or attempt + 1 == attempts:
                raise DownloadError("cannot download {}: {}".format(url, error)) from error
            delay = retry_delay(error, attempt)
            print("cannot download {}: {}; retrying in {} s".format(url, error, delay), file=sys.stderr)
            sleep(delay)
    raise DownloadError("cannot download {}: no attempts".format(url))
