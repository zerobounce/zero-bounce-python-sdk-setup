"""Streamed downloads (opt-in) and the regional base_url warning."""

import io
import json
import tempfile
import warnings
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from requests import Response
from requests.exceptions import ChunkedEncodingError

from zerobouncesdk import ZBApiException, ZBApiUrl, ZeroBounce

KEY = "secret-key-123"
CSV = b"email,status\n" + b"".join(b"user%06d@example.com,valid\n" % i for i in range(20000))  # ~600 KB


def _streamed(status, body, content_type, raw=None):
    """A response whose body is read from ``raw`` as requests does with stream=True."""
    response = Response()
    response.status_code = status
    response.headers["Content-Type"] = content_type
    response.raw = raw if raw is not None else io.BytesIO(body)
    response.encoding = "utf-8"
    return response


class _FailingRaw(io.BytesIO):
    """Serves some bytes, then the connection drops."""

    def read(self, *args, **kwargs):
        data = super().read(*args, **kwargs)
        if self.tell() > 100_000:
            raise ChunkedEncodingError(f"Connection broken: https://bulkapi.zerobounce.net/v2/getfile?api_key={KEY}")
        return data


class StreamedDownloadTest(TestCase):
    def setUp(self):
        self.calls = []
        self.reply = lambda request: _streamed(200, CSV, "text/csv")

        def send(session, request, **kwargs):
            self.calls.append(kwargs.get("stream"))
            return self.reply(request)

        patcher = patch("requests.sessions.Session.send", send)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = ZeroBounce(KEY)
        self.folder = Path(tempfile.mkdtemp())

    def _leftovers(self):
        return [p.name for p in self.folder.rglob("*.part")]

    def test_every_download_method_streams_when_asked(self):
        for name, call in (
            ("get_file", lambda path: self.client.get_file("file-9", path, stream=True)),
            ("scoring_get_file", lambda path: self.client.scoring_get_file("file-9", path, stream=True)),
            ("email_finder_get_file", lambda path: self.client.email_finder_get_file("file-9", path, stream=True)),
            ("domain_search_get_file", lambda path: self.client.domain_search_get_file("file-9", path, stream=True)),
        ):
            path = self.folder / "nested" / f"{name}.csv"
            result = call(str(path))
            self.assertEqual(result.local_file_path, str(path))
            self.assertEqual(path.read_bytes(), CSV, name)
        self.assertEqual(self.calls, [True] * 4)
        self.assertEqual(self._leftovers(), [])

    def test_without_the_flag_nothing_changes(self):
        self.reply = lambda request: _streamed(200, CSV, "text/csv")
        path = self.folder / "buffered.csv"
        self.client.get_file("file-9", str(path))
        self.assertEqual(path.read_bytes(), CSV)
        self.assertEqual(self.calls, [False])  # requests' default: the body is read into memory

    def test_error_bodies_raise_and_leave_no_file(self):
        cases = [
            (200, json.dumps({"success": False, "message": "File cannot be found."}).encode(), "application/json", "File cannot be found."),
            (403, b"<!DOCTYPE html><html><head><title>Access denied</title></head>" + b"x" * 3_000_000, "text/html", "Access denied"),
            (200, b"<html><title>Not a file</title></html>", "text/html", "Not a file"),
            (200, b"", "text/csv", "Empty response"),
            (302, b"", "text/plain", "redirect"),
        ]
        for status, body, content_type, expected in cases:
            self.reply = lambda request, s=status, b=body, c=content_type: _streamed(s, b, c)
            path = self.folder / "result.csv"
            with self.assertRaises(ZBApiException) as caught:
                self.client.get_file("file-9", str(path), stream=True)
            self.assertIn(expected, str(caught.exception))
            self.assertLess(len(str(caught.exception)), 300)
            self.assertFalse(path.exists(), status)
            self.assertEqual(self._leftovers(), [])

    def test_a_dropped_connection_is_redacted_and_leaves_no_partial_file(self):
        self.reply = lambda request: _streamed(200, b"", "text/csv", raw=_FailingRaw(CSV))
        path = self.folder / "result.csv"
        with self.assertRaises(ChunkedEncodingError) as caught:
            self.client.get_file("file-9", str(path), stream=True)
        self.assertNotIn(KEY, str(caught.exception))
        self.assertIsNone(caught.exception.__context__)
        self.assertFalse(path.exists())
        self.assertEqual(self._leftovers(), [])

    def test_an_existing_file_is_only_replaced_by_a_complete_download(self):
        path = self.folder / "result.csv"
        path.write_bytes(b"previous results\n")
        self.reply = lambda request: _streamed(200, b"", "text/csv", raw=_FailingRaw(CSV))
        with self.assertRaises(ChunkedEncodingError):
            self.client.get_file("file-9", str(path), stream=True)
        self.assertEqual(path.read_bytes(), b"previous results\n")


class RegionalBaseUrlTest(TestCase):
    def setUp(self):
        def send(session, request, **kwargs):
            return _streamed(200, json.dumps({"success": True, "file_status": "Complete"}).encode(), "application/json")

        patcher = patch("requests.sessions.Session.send", send)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _warnings(self, client, calls):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for call in calls:
                call(client)
        return [w for w in caught if "regional host" in str(w.message)]

    def test_a_regional_base_url_warns_once_about_the_global_bulk_host(self):
        for region in (ZBApiUrl.API_EU_URL, ZBApiUrl.API_USA_URL, "https://api-eu.zerobounce.net/v2"):
            client = ZeroBounce(KEY, base_url=region)
            found = self._warnings(client, [lambda c: c.file_status("f1"), lambda c: c.scoring_file_status("f1")])
            self.assertEqual(len(found), 1, region)
            self.assertIn("bulkapi.zerobounce.net", str(found[0].message))
            self.assertNotIn(KEY, str(found[0].message))

    def test_no_warning_for_the_default_host_or_single_requests_or_regional_bulk_urls(self):
        self.assertEqual(self._warnings(ZeroBounce(KEY), [lambda c: c.file_status("f1")]), [])
        self.assertEqual(self._warnings(ZeroBounce(KEY, base_url=ZBApiUrl.API_EU_URL), [lambda c: c.get_credits()]), [])
        client = ZeroBounce(KEY, base_url=ZBApiUrl.API_EU_URL)
        client.BULK_BASE_URL = "https://bulkapi-eu.example.com/v2"
        self.assertEqual(self._warnings(client, [lambda c: c.file_status("f1")]), [])
