"""Transport guards on every request path: redirects, timeouts and result-file errors.

The sweeps enumerate every public request method of ``ZeroBounce`` (the HTTPS sweep's call list) and of
``ZeroBounceWarmup`` (the list below), each with a guard that fails when a method is missing from it.
"""

import contextlib
import errno
import io
import os
import socket
import tempfile
import threading
import traceback
import warnings
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

from requests import Response
from requests.exceptions import RequestException

from tests import test_standard_parity_offline as parity
from zerobouncesdk import ZBApiException, ZeroBounce, ZeroBounceWarmup

try:
    import resource
except ImportError:  # Windows has no file size limit to set
    resource = None

KEY = "guard-key-123"
_BASE_URL_ATTRIBUTES = {
    "BULK_BASE_URL": "/v2",
    "BULK_ROOT_URL": "",
    "SCORING_BASE_URL": "/v2/scoring",
    "EMAIL_FINDER_BASE_URL": "/email-finder",
    "DOMAIN_SEARCH_BASE_URL": "/domain-search",
    "LIST_EVALUATOR_BASE_URL": "/v2/listevaluator",
    "INBOX_PLACEMENT_BASE_URL": "/api/ipt",
}


def client_calls(client, out):
    """Every public request method of ZeroBounce, from the HTTPS sweep (which guards its completeness)."""
    return parity.HttpsSweepTest.calls(None, client, out)


def warmup_calls(out):
    """Every public method of ZeroBounceWarmup, called once."""
    return {
        "list_sending_accounts": lambda w: w.list_sending_accounts(),
        "get_sending_account": lambda w: w.get_sending_account("a@example.com"),
        "add_sending_account": lambda w: w.add_sending_account("a@example.com", "self_managed", engagement_rule_id=0),
        "update_sending_account": lambda w: w.update_sending_account("a@example.com", 1, 1, False),
        "delete_sending_account": lambda w: w.delete_sending_account("a@example.com"),
        "change_from_address": lambda w: w.change_from_address("a@example.com", "b@example.com"),
        "list_from_addresses": lambda w: w.list_from_addresses(),
        "get_engagement_rules": lambda w: w.get_engagement_rules(),
        "set_engagement_rule": lambda w: w.set_engagement_rule("a@example.com", 2),
        "get_custom_engagement": lambda w: w.get_custom_engagement("a@example.com"),
        "create_custom_engagement": lambda w: w.create_custom_engagement("a@example.com", 20, 25, 25),
        "update_custom_engagement": lambda w: w.update_custom_engagement("a@example.com", 20, 25, 25),
        "delete_custom_engagement": lambda w: w.delete_custom_engagement("a@example.com", 1),
        "get_seeds": lambda w: w.get_seeds(),
        "download_seeds": lambda w: w.download_seeds(out),
        "get_seed_count": lambda w: w.get_seed_count(),
        "get_progress_today": lambda w: w.get_progress_today(),
        "get_sent_today": lambda w: w.get_sent_today(),
        "get_emails_per_day": lambda w: w.get_emails_per_day(),
        "get_statistics": lambda w: w.get_statistics("a@example.com"),
        "get_statistics_per_day": lambda w: w.get_statistics_per_day("a@example.com", "2026-09-01", "2026-09-14"),
        "get_statistics_detailed": lambda w: w.get_statistics_detailed("a@example.com"),
        "download_statistics": lambda w: w.download_statistics("a@example.com", out),
        "get_from_address_statistics": lambda w: w.get_from_address_statistics("a@example.com"),
        "check_domain_dmarc": lambda w: w.check_domain_dmarc("a@example.com"),
        "test_smtp_configuration": lambda w: w.test_smtp_configuration(
            "a@example.com", "user", "pw", "smtp.example.com", 587
        ),
    }


def _public(cls, not_requests=()):
    return {
        name for name in dir(cls) if not name.startswith("_") and callable(getattr(cls, name))
    } - set(not_requests)


class LocalServer:
    """A real HTTP server on a loopback port. ``answer(handler)`` returns (status, headers, body)."""

    def __init__(self, answer):
        self.hits = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _any(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                server.hits.append(f"{self.command} {self.path}")
                status, headers, body = answer(self)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PUT = do_DELETE = _any

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _quiet(call):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # guess_format is deprecated and says so
        return call()


class SweepCompletenessTest(TestCase):
    def test_the_warmup_sweep_covers_every_public_method(self):
        self.assertEqual(_public(ZeroBounceWarmup) - set(warmup_calls("x.csv")), set())


class RedirectSweepTest(TestCase):
    """A 3xx WITH a Location header from a real server: following it would send the key to a second host."""

    STATUSES = (301, 302, 303, 307, 308)

    def setUp(self):
        self.status = 302
        self.second = LocalServer(lambda h: (200, {"Content-Type": "application/json"}, b'{"Credits":"999"}'))
        self.first = LocalServer(
            lambda h: (self.status, {"Location": f"{self.second.url}/landed", "Content-Type": "text/plain"}, b"")
        )
        self.addCleanup(self.first.close)
        self.addCleanup(self.second.close)
        # Plain http to the loopback servers; https is enforced by its own sweep.
        patcher = patch("zerobouncesdk.zerobouncesdk._https_url", lambda url: url)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.out = str(Path(tempfile.mkdtemp()) / "out.csv")

    def _refused(self, name, call):
        for status in self.STATUSES:
            self.status = status
            before = len(self.first.hits)
            with self.assertRaises(ZBApiException, msg=f"{name} {status}") as caught:
                _quiet(call)
            self.assertEqual(caught.exception.status_code, status, name)
            self.assertGreater(len(self.first.hits), before, f"{name} sent nothing")
            self.assertEqual(self.second.hits, [], f"{name} followed a {status}")

    def test_no_client_request_follows_a_redirect(self):
        client = ZeroBounce(KEY)
        client._base_url = self.first.url + "/v2"
        for attribute, path in _BASE_URL_ATTRIBUTES.items():
            setattr(client, attribute, self.first.url + path)
        calls = client_calls(client, self.out)
        self.assertEqual(_public(ZeroBounce, parity.HttpsSweepTest.NOT_REQUESTS) - set(calls), set())
        for name, variants in calls.items():
            for call in variants:
                self._refused(name, call)

    def test_no_warmup_request_follows_a_redirect(self):
        warmup = ZeroBounceWarmup(KEY)
        warmup._root = self.first.url + ZeroBounceWarmup.BASE_PATH
        for name, call in warmup_calls(self.out).items():
            self._refused(name, lambda c=call: c(warmup))



class RawSocketServer:
    """A loopback HTTP server on a raw socket: reads each whole request, writes ``answer(request_line)`` and
    closes the connection, so a response can promise more bytes than it sends."""

    def __init__(self, answer):
        self.hits = []
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.url = f"http://127.0.0.1:{self._sock.getsockname()[1]}"
        self._answer = answer
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self):
        self._sock.close()

    def _serve(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._reply, args=(conn,), daemon=True).start()

    def _reply(self, conn):
        with conn:
            conn.settimeout(5)
            line = self._read_request(conn)
            self.hits.append(line)
            conn.sendall(self._answer(line))
            # Read until the client hangs up, so closing never resets a connection it is still reading.
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_WR)
                while conn.recv(65536):
                    pass

    @staticmethod
    def _read_request(conn):
        """The request line, after the headers and the whole body (Content-Length or chunked) are read."""
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        headers = head.decode("latin-1").lower()
        length = 0
        for header in headers.split("\r\n")[1:]:
            name, _, value = header.partition(":")
            if name.strip() == "content-length":
                length = int(value)
        if "transfer-encoding: chunked" in headers:
            while not body.endswith(b"0\r\n\r\n"):
                body += conn.recv(65536)
        while len(body) < length:
            chunk = conn.recv(65536)
            if not chunk:
                break
            body += chunk
        return head.split(b"\r\n", 1)[0].decode("latin-1")


class CutShortBodySweepTest(TestCase):
    """A 200 whose body is cut short is an error on every request path, including downloads (streamed or not)
    and Warmup, and leaves no file behind. The fake sends a valid 25-byte JSON or CSV body that would read as a
    complete result, then closes the connection: only the length check (``Content-Length``, or a chunked body
    missing its last chunk) tells the transfer was broken."""

    CSV = b"email,status\na@b.c,valid\n"  # 25 bytes
    JSON = b'{"Credits":"5","a":"bbb"}'  # 25 bytes, valid JSON on its own

    def setUp(self):
        self.mode = "length"
        self.server = RawSocketServer(self._answer)
        self.addCleanup(self.server.close)
        # Plain http to the loopback server; https is enforced by its own sweep.
        patcher = patch("zerobouncesdk.zerobouncesdk._https_url", lambda url: url)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = Path(tempfile.mkdtemp())
        self.out = str(self.folder / "out.csv")

    def _answer(self, request_line):
        download = "getfile" in request_line or "/download" in request_line
        content_type, body = ("text/csv", self.CSV) if download else ("application/json", self.JSON)
        if self.mode == "length":
            head = f"Content-Length: {len(body) + 975}"
        else:  # chunked: one complete chunk, then the connection closes without the last (empty) chunk
            head = "Transfer-Encoding: chunked"
            body = b"%x\r\n%s\r\n" % (len(body), body)
        return f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\n{head}\r\nConnection: close\r\n\r\n".encode() + body

    def _client_calls(self):
        client = ZeroBounce(KEY, timeout=timedelta(seconds=5))
        client._base_url = self.server.url + "/v2"
        for attribute, path in _BASE_URL_ATTRIBUTES.items():
            setattr(client, attribute, self.server.url + path)
        calls = client_calls(client, self.out)
        self.assertEqual(_public(ZeroBounce, parity.HttpsSweepTest.NOT_REQUESTS) - set(calls), set())
        # Every download, streamed too.
        for name in [name for name in calls if name.endswith("get_file")]:
            calls[name] = [
                lambda m=getattr(client, name): m("f1", self.out),
                lambda m=getattr(client, name): m("f1", self.out, stream=True),
            ]
        return calls

    def _warmup_calls(self):
        warmup = ZeroBounceWarmup(KEY, timeout=timedelta(seconds=5))
        warmup._root = self.server.url + ZeroBounceWarmup.BASE_PATH
        return {name: [lambda c=call: c(warmup)] for name, call in warmup_calls(self.out).items()}

    def _sweep(self, calls):
        for mode in ("length", "chunked"):
            self.mode = mode
            for name, variants in calls.items():
                for call in variants:
                    before = len(self.server.hits)
                    with self.assertRaises(RequestException, msg=f"{name} ({mode})") as caught:
                        _quiet(call)
                    self.assertGreater(len(self.server.hits), before, f"{name} sent nothing")
                    self.assertNotIn(KEY, str(caught.exception), name)
                    self.assertEqual(list(self.folder.iterdir()), [], f"{name} ({mode}) left a file behind")

    def test_every_client_request(self):
        self._sweep(self._client_calls())

    def test_every_warmup_request(self):
        self._sweep(self._warmup_calls())

class TimeoutSweepTest(TestCase):
    """Every request goes out with the client's timeout (requests has none by default)."""

    def setUp(self):
        self.sent = []

        def send(session, request, **kwargs):
            self.sent.append(kwargs)
            response = Response()
            response.status_code = 200
            response._content = b'{"success": true}'
            response._content_consumed = True
            response.headers["Content-Type"] = "application/json"
            response.url = request.url
            response.request = request
            return response

        patcher = patch("requests.sessions.Session.send", send)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.out = str(Path(tempfile.mkdtemp()) / "out.csv")

    def _check(self, name, call, expected):
        self.sent.clear()
        try:
            _quiet(call)
        except ZBApiException:
            pass  # a JSON answer to a download; only the request options matter here
        self.assertTrue(self.sent, f"{name} sent nothing")
        for kwargs in self.sent:
            self.assertEqual(kwargs.get("timeout"), expected, name)

    def test_every_client_request_has_the_timeout(self):
        client = ZeroBounce(KEY, timeout=timedelta(milliseconds=1234))
        for name, variants in client_calls(client, self.out).items():
            for call in variants:
                self._check(name, call, 1.234)

    def test_every_warmup_request_has_the_timeout(self):
        warmup = ZeroBounceWarmup(KEY, timeout=timedelta(milliseconds=1234))
        for name, call in warmup_calls(self.out).items():
            self._check(name, lambda c=call: c(warmup), 1.234)

    def test_the_default_timeouts_are_sent(self):
        # The clients the public constructors build, without a timeout argument: 120 seconds on every request.
        client = ZeroBounce(KEY)
        for name, variants in client_calls(client, self.out).items():
            for call in variants:
                self._check(name, call, 120.0)
        warmup = ZeroBounceWarmup(KEY)
        for name, call in warmup_calls(self.out).items():
            self._check(name, lambda c=call: c(warmup), 120.0)


def _file_reply(status, body, content_type):
    def send(session, request, **kwargs):
        response = Response()
        response.status_code = status
        response.headers["Content-Type"] = content_type
        response.raw = io.BytesIO(body)
        response.encoding = "utf-8"
        response.url = request.url
        return response

    return send


class ResultFileErrorTest(TestCase):
    def setUp(self):
        self.client = ZeroBounce(KEY)
        self.folder = Path(tempfile.mkdtemp())
        self.downloads = {
            "get_file": self.client.get_file,
            "scoring_get_file": self.client.scoring_get_file,
            "email_finder_get_file": self.client.email_finder_get_file,
            "domain_search_get_file": self.client.domain_search_get_file,
        }

    def test_an_http_error_with_a_plain_text_body_is_not_saved(self):
        # Neither HTML nor JSON: only the status says it is not a result file.
        for status in (404, 500, 503):
            with patch("requests.sessions.Session.send", _file_reply(status, b"Internal error\n", "text/plain")):
                for name, download in self.downloads.items():
                    for stream in (False, True):
                        path = self.folder / f"{name}-{status}-{stream}.csv"
                        with self.assertRaises(ZBApiException, msg=name) as caught:
                            download("f1", str(path), stream=stream)
                        self.assertEqual(caught.exception.status_code, status, name)
                        self.assertFalse(path.exists(), f"{name} saved an HTTP {status} (stream={stream})")

    def _downloads_into(self, folder, existing):
        """Every download, streamed and not, plus the Warmup CSVs, each into a file already holding ``existing``."""
        warmup = ZeroBounceWarmup(KEY)
        calls = {}
        for name, download in self.downloads.items():
            for stream in (False, True):
                calls[f"{name} stream={stream}"] = lambda path, d=download, s=stream: d("f1", path, stream=s)
        calls["download_seeds"] = warmup.download_seeds
        calls["download_statistics"] = lambda path: warmup.download_statistics("a@example.com", path)
        paths = {}
        for name in calls:
            paths[name] = folder / f"{name.replace(' ', '-')}.csv"
            paths[name].write_bytes(existing)
        return calls, paths

    @skipUnless(resource is not None, "needs RLIMIT_FSIZE")
    def test_a_failed_write_keeps_an_existing_file_and_leaves_no_partial_file(self):
        # A real write failure: the process may not write files larger than the limit (ulimit -f), so the
        # write fails with EFBIG part-way through, as on a full disk.
        csv = b"email,status\n" + b"a@example.com,valid\n" * 10_000
        calls, paths = self._downloads_into(self.folder, b"keep me\n")
        soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        failed = {}
        with patch("requests.sessions.Session.send", _file_reply(200, csv, "text/csv")):
            for name, download in calls.items():
                resource.setrlimit(resource.RLIMIT_FSIZE, (len(csv) // 2, hard))
                try:
                    download(str(paths[name]))
                except OSError as error:
                    failed[name] = error.errno
                finally:
                    resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
        self.assertEqual(failed, {name: errno.EFBIG for name in calls})
        for name, path in paths.items():
            self.assertEqual(path.read_bytes(), b"keep me\n", f"{name} truncated or deleted the existing file")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), sorted(p.name for p in paths.values()))

    @skipUnless(hasattr(os, "geteuid") and os.geteuid() != 0, "root writes into a read-only folder")
    def test_a_read_only_folder_keeps_the_existing_file(self):
        folder = self.folder / "read-only"
        folder.mkdir()
        calls, paths = self._downloads_into(folder, b"keep me\n")
        folder.chmod(0o555)
        self.addCleanup(folder.chmod, 0o755)
        with patch("requests.sessions.Session.send", _file_reply(200, b"email\na@example.com\n", "text/csv")):
            for name, download in calls.items():
                with self.assertRaises(PermissionError, msg=name):
                    download(str(paths[name]))
                self.assertEqual(paths[name].read_bytes(), b"keep me\n", name)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(p.name for p in paths.values()))

    def test_a_complete_download_replaces_an_existing_file(self):
        csv = b"email,status\na@example.com,valid\n"
        calls, paths = self._downloads_into(self.folder, b"old result\n")
        with patch("requests.sessions.Session.send", _file_reply(200, csv, "text/csv")):
            for name, download in calls.items():
                download(str(paths[name]))
                self.assertEqual(paths[name].read_bytes(), csv, name)
                if os.name == "posix":  # the usual mode for a new file, not the temporary file's 0600
                    umask = os.umask(0)
                    os.umask(umask)
                    self.assertEqual(paths[name].stat().st_mode & 0o777, 0o666 & ~umask, name)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), sorted(p.name for p in paths.values()))

    def test_a_json_content_type_alone_is_an_error(self):
        # The body reads as CSV; only the content type says it is a JSON answer. Streamed and not, and Warmup.
        calls, paths = self._downloads_into(self.folder, b"keep me\n")
        with patch(
            "requests.sessions.Session.send", _file_reply(200, b"email,status\na@example.com,valid\n", "application/json")
        ):
            for name, download in calls.items():
                with self.assertRaises(ZBApiException, msg=name) as caught:
                    download(str(paths[name]))
                self.assertEqual(caught.exception.status_code, 200, name)
                self.assertEqual(paths[name].read_bytes(), b"keep me\n", name)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), sorted(p.name for p in paths.values()))

    def test_a_json_error_under_a_csv_content_type_is_not_saved(self):
        # The content type says CSV, but the body is the API's JSON error: only the body tells them apart.
        # Every download, streamed and not, found from the public methods.
        downloads = sorted(name for name in _public(ZeroBounce) if name.endswith("get_file"))
        self.assertEqual(set(downloads), set(self.downloads))
        bodies = (
            b'{"success": false, "message": "File cannot be found."}',
            b'  \n{"error": "File cannot be found."}',
        )
        for body in bodies:
            with patch("requests.sessions.Session.send", _file_reply(200, body, "text/csv")):
                for name in downloads:
                    for stream in (False, True):
                        path = self.folder / f"{name}-{stream}.csv"
                        with self.assertRaises(ZBApiException, msg=f"{name} stream={stream} {body!r}") as caught:
                            getattr(self.client, name)("f1", str(path), stream=stream)
                        self.assertEqual(caught.exception.status_code, 200)
                        self.assertFalse(path.exists(), f"{name} saved a JSON error (stream={stream})")
                        self.assertEqual(
                            [p for p in self.folder.iterdir() if p.name.startswith(".zb-download-")], [],
                            f"{name} left a partial file",
                        )


class WarmupCsvWriteTest(TestCase):
    """A Warmup CSV saved to download_path: a failed write must not leave a truncated file behind."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.warmup = ZeroBounceWarmup(KEY)
        self.csv = b"seed,provider\n" + b"seed@example.org,gmail\n" * 100
        patcher = patch("requests.sessions.Session.send", _file_reply(200, self.csv, "text/csv"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.downloads = {
            "download_seeds": lambda path: self.warmup.download_seeds(path),
            "download_statistics": lambda path: self.warmup.download_statistics("a@example.com", path),
        }

    def test_a_failed_write_leaves_no_partial_file(self):
        class DiskFull(io.FileIO):
            def write(self, data):
                super().write(bytes(data[:10]))
                raise OSError(errno.ENOSPC, "No space left on device")

        def disk_full_open(path, mode="r", *args, **kwargs):
            return DiskFull(path, mode.replace("b", ""))

        with patch("zerobouncesdk.zb_warmup.open", disk_full_open, create=True):
            for name, download in self.downloads.items():
                path = self.folder / f"{name}.csv"
                with self.assertRaises(OSError, msg=name) as caught:
                    download(str(path))
                self.assertEqual(caught.exception.errno, errno.ENOSPC)
                self.assertFalse(path.exists(), f"{name} left a partial file")

    def test_a_file_that_cannot_be_opened_is_left_alone(self):
        path = self.folder / "existing.csv"
        path.write_bytes(b"keep me\n")

        def refuse(path, mode="r", *args, **kwargs):
            raise PermissionError(errno.EACCES, "Permission denied", path)

        with patch("zerobouncesdk.zb_warmup.open", refuse, create=True):
            with self.assertRaises(PermissionError):
                self.warmup.download_seeds(str(path))
        self.assertEqual(path.read_bytes(), b"keep me\n")

    def test_a_failed_write_keeps_an_existing_file(self):
        class DiskFull(io.FileIO):
            def write(self, data):
                super().write(bytes(data[:10]))
                raise OSError(errno.ENOSPC, "No space left on device")

        def disk_full_open(path, mode="r", *args, **kwargs):
            return DiskFull(path, mode.replace("b", ""))

        with patch("zerobouncesdk.zb_warmup.open", disk_full_open, create=True):
            for name, download in self.downloads.items():
                path = self.folder / f"{name}.csv"
                path.write_bytes(b"keep me\n")
                with self.assertRaises(OSError, msg=name):
                    download(str(path))
                self.assertEqual(path.read_bytes(), b"keep me\n", f"{name} truncated or deleted the existing file")
                self.assertEqual([p.name for p in self.folder.iterdir() if p.name.startswith(".zb-")], [], name)

    def test_a_json_body_under_a_csv_content_type_is_an_error(self):
        # The content type says CSV, but the body is JSON: an API error, never a CSV, and nothing is written.
        for body in (b'{"error": "c_from not found"}', b'  \n{"success": false, "message": "no seeds"}', b'[]'):
            with patch("requests.sessions.Session.send", _file_reply(200, body, "text/csv")):
                for name, download in self.downloads.items():
                    path = self.folder / f"{name}.csv"
                    path.write_bytes(b"keep me\n")
                    with self.assertRaises(ZBApiException, msg=f"{name} {body!r}") as caught:
                        download(str(path))
                    self.assertEqual(caught.exception.status_code, 200)
                    self.assertEqual(path.read_bytes(), b"keep me\n", name)
                    with self.assertRaises(ZBApiException, msg=f"{name} {body!r} without a path"):
                        download(None)

    def test_a_complete_write_is_kept(self):
        for name, download in self.downloads.items():
            path = self.folder / "nested" / f"{name}.csv"
            self.assertEqual(download(str(path)), self.csv.decode())
            self.assertEqual(path.read_bytes(), self.csv)


class InboxPlacementDeleteTest(TestCase):
    """DELETE /api/ipt/test/{id} may answer 204 No Content: a success, as in the Go SDK."""

    def test_an_empty_2xx_is_a_success(self):
        for status in (200, 202, 204):
            with patch("requests.sessions.Session.send", _file_reply(status, b"", "text/plain")):
                self.assertIsNone(ZeroBounce(KEY).delete_inbox_placement_test(7))

    def test_a_json_answer_is_still_returned(self):
        with patch("requests.sessions.Session.send", _file_reply(200, b'{"deleted": true}', "application/json")):
            self.assertEqual(ZeroBounce(KEY).delete_inbox_placement_test(7), {"deleted": True})

    def test_errors_and_other_calls_are_unchanged(self):
        with patch("requests.sessions.Session.send", _file_reply(404, b"", "text/plain")):
            with self.assertRaises(ZBApiException) as caught:
                ZeroBounce(KEY).delete_inbox_placement_test(7)
            self.assertEqual(caught.exception.status_code, 404)
        with patch("requests.sessions.Session.send", _file_reply(200, b"<html><title>x</title></html>", "text/html")):
            with self.assertRaises(ZBApiException):
                ZeroBounce(KEY).delete_inbox_placement_test(7)
        with patch("requests.sessions.Session.send", _file_reply(204, b"", "text/plain")):
            with self.assertRaises(ZBApiException):
                ZeroBounce(KEY).get_inbox_placement_test(7)


class KeyEchoSweepTest(TestCase):
    """A response body that quotes the key (an API message naming it, a proxy echoing the request URL, an HTML
    title) never hands it to the caller: no error from any public method of either client carries it, in its
    raw or URL-encoded form, in its message, repr, attributes, or its cause or context."""

    ECHO_KEY = "echo+key/42"
    ENCODED = "echo%2Bkey%2F42"
    JSON = "application/json"
    BODIES = {
        '200 {"error"}': (200, JSON, '{"error":"Invalid API key %s"}' % ECHO_KEY),
        '200 {"success":false}': (200, JSON, '{"success":false,"message":"Invalid API key %s"}' % ECHO_KEY),
        '200 batch "all" error': (
            200, JSON, '{"email_batch":[],"errors":[{"email_address":"all","error":"Invalid API key %s"}]}' % ECHO_KEY
        ),
        "200 HTML title": (200, "text/html", "<html><head><title>Denied %s</title></head></html>" % ECHO_KEY),
        "200 JSON cut off": (200, JSON, '{"error":"Invalid API key %s"' % ECHO_KEY),
        "400 text quoting the URL": (400, "text/plain", "Bad request: https://x.example/v2/x?api_key=" + ENCODED),
        '400 {"error"}': (400, JSON, '{"error":"Invalid API key %s"}' % ECHO_KEY),
    }

    def setUp(self):
        self.answer = self.BODIES['200 {"error"}']
        self.server = LocalServer(lambda h: (self.answer[0], {"Content-Type": self.answer[1]}, self.answer[2].encode()))
        self.addCleanup(self.server.close)
        # Plain http to the loopback server; https is enforced by its own sweep.
        patcher = patch("zerobouncesdk.zerobouncesdk._https_url", lambda url: url)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = Path(tempfile.mkdtemp())
        self.out = str(self.folder / "out.csv")

    def _visible(self, error):
        """Everything a caller or a traceback printer can read off the error, its cause and context included."""
        parts = ["".join(traceback.format_exception(type(error), error, error.__traceback__))]
        seen = error
        while seen is not None:
            parts += [repr(seen), repr(seen.args), repr(vars(seen))]
            seen = seen.__cause__ or seen.__context__
        return "\n".join(parts)

    def _sweep(self, calls, must_raise):
        for label, answer in self.BODIES.items():
            self.answer = answer
            for name, variants in calls.items():
                for call in variants:
                    try:
                        _quiet(call)
                    except Exception as error:  # noqa: BLE001 - every error is checked
                        text = self._visible(error)
                        self.assertNotIn(self.ECHO_KEY, text, f"{name}: {label}")
                        self.assertNotIn(self.ENCODED, text, f"{name}: {label}")
                    else:
                        self.assertNotIn(label, must_raise, f"{name} returned for {label}")
            self.assertEqual(list(self.folder.iterdir()), [], f"a file was saved for {label}")

    def test_every_client_request(self):
        client = ZeroBounce(self.ECHO_KEY, timeout=timedelta(seconds=5))
        client._base_url = self.server.url + "/v2"
        for attribute, path in _BASE_URL_ATTRIBUTES.items():
            setattr(client, attribute, self.server.url + path)
        calls = client_calls(client, self.out)
        self.assertEqual(_public(ZeroBounce, parity.HttpsSweepTest.NOT_REQUESTS) - set(calls), set())
        for name in [name for name in calls if name.endswith("get_file")]:
            calls[name] = [
                lambda m=getattr(client, name): m("f1", self.out),
                lambda m=getattr(client, name): m("f1", self.out, stream=True),
            ]
        # Each of these bodies is an error on every call of the client.
        self._sweep(calls, must_raise=set(self.BODIES) - {'200 batch "all" error'})

    def test_every_warmup_request(self):
        warmup = ZeroBounceWarmup(self.ECHO_KEY, timeout=timedelta(seconds=5))
        warmup._root = self.server.url + ZeroBounceWarmup.BASE_PATH
        calls = {name: [lambda c=call: c(warmup)] for name, call in warmup_calls(self.out).items()}
        # A 200 JSON body is a Warmup result, whatever it says.
        self._sweep(calls, must_raise={"200 HTML title", "200 JSON cut off", "400 text quoting the URL", '400 {"error"}'})


class HtmlContentTypeTest(TestCase):
    """A text/html answer is an error by its content type alone, even when the body has no HTML tags."""

    def test_json_calls_and_downloads_reject_text_html(self):
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        client = ZeroBounce(KEY)
        warmup = ZeroBounceWarmup(KEY)
        calls = [(name, call) for name, variants in client_calls(client, out).items() for call in variants]
        calls += [(name, lambda c=call: c(warmup)) for name, call in warmup_calls(out).items()]
        # A body every path would otherwise accept: JSON for the JSON calls, a CSV line for the downloads.
        for body in (b'{"success": true, "Credits": "5", "file_id": "f1"}', b"email,status\na@example.com,valid\n"):
            with patch("requests.sessions.Session.send", _file_reply(200, body, "text/html; charset=utf-8")):
                accepted = []
                for name, call in calls:
                    if name.endswith("get_file") or name.startswith("download_"):
                        if body.startswith(b"{"):
                            continue  # a JSON body is rejected as JSON anyway
                    elif not body.startswith(b"{"):
                        continue  # a CSV body is rejected as non-JSON anyway
                    try:
                        _quiet(call)
                    except ZBApiException as error:
                        self.assertEqual(error.status_code, 200, name)
                    except Exception:  # noqa: BLE001 - another error is not an acceptance
                        pass
                    else:
                        accepted.append(name)
                self.assertEqual(accepted, [], body)


class StrictJsonTest(TestCase):
    """E7: a 2xx body that is not strict RFC 8259 JSON is an API error with status 200 on every call.

    ``json.loads`` (and ``requests``' ``Response.json``) accept ``NaN``, ``Infinity`` and ``-Infinity`` by default.
    """

    BODIES = (
        b"NaN",
        b"Infinity",
        b"-Infinity",
        b'{"success": true, "Credits": NaN, "file_id": "f1"}',
        b'{"success": true, "Credits": -Infinity, "file_id": "f1"}',
        b"{a:1}",
        b"[1,]",
        b"123abc",
        b'{"success": true, "Credits": "5", "file_id": "f1"} junk',
    )

    def test_every_call_rejects_a_body_that_is_not_strict_json(self):
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        client = ZeroBounce(KEY)
        warmup = ZeroBounceWarmup(KEY)
        calls = [(name, call) for name, variants in client_calls(client, out).items() for call in variants]
        calls += [(f"warmup.{name}", lambda c=call: c(warmup)) for name, call in warmup_calls(out).items()]
        accepted = []
        for body in self.BODIES:
            with patch("requests.sessions.Session.send", _file_reply(200, body, "application/json")):
                for name, call in calls:
                    try:
                        _quiet(call)
                    except ZBApiException as error:
                        if error.status_code != 200:
                            accepted.append((name, body, error.status_code))
                    except Exception as error:  # noqa: BLE001 - any other error is a wrong answer too
                        accepted.append((name, body, type(error).__name__))
                    else:
                        accepted.append((name, body))
        self.assertEqual(accepted, [])


# tests/fixtures/strict-json-corpus.tsv is a byte-identical copy of
# sdk-docs/skills/zerobounce-sdk/references/strict-json-corpus.tsv (zerobounce/sdk-docs); refresh it from there.
_CORPUS = Path(__file__).parent / "fixtures" / "strict-json-corpus.tsv"


def strict_json_corpus():
    """(verdict, body) pairs: each line's second field is a JSON-encoded string holding the exact body."""
    import json

    rows = []
    for line in _CORPUS.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            verdict, encoded = line.split("\t", 1)
            rows.append((verdict, json.loads(encoded).encode("utf-8")))
    return rows


class StrictJsonCorpusTest(TestCase):
    """E7: every JSON call rejects every REJECT body of the shared corpus (an API error with status 200) and
    rejects no ACCEPT body as an API error.

    Downloads are not JSON calls (any JSON body is an error there). An empty 200 (zero bytes) is the documented
    empty success of the Warmup calls and of ``delete_inbox_placement_test`` (check E8), so those skip that one
    body; a blank body is never empty.
    """

    DOWNLOADS = {
        "get_file", "scoring_get_file", "email_finder_get_file", "domain_search_get_file",
        "warmup.download_seeds", "warmup.download_statistics",
    }

    def _calls(self):
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        client = ZeroBounce(KEY)
        warmup = ZeroBounceWarmup(KEY)
        calls = [(name, call) for name, variants in client_calls(client, out).items() for call in variants]
        calls += [(f"warmup.{name}", lambda c=call: c(warmup)) for name, call in warmup_calls(out).items()]
        return [(name, call) for name, call in calls if name not in self.DOWNLOADS]

    @staticmethod
    def _empty_success(name, body):
        return body == b"" and (name.startswith("warmup.") or name == "delete_inbox_placement_test")

    def test_the_corpus_has_both_verdicts(self):
        verdicts = [verdict for verdict, _ in strict_json_corpus()]
        self.assertEqual(set(verdicts), {"REJECT", "ACCEPT"})
        self.assertGreater(verdicts.count("REJECT"), 30)

    def test_every_json_call_rejects_every_reject_body(self):
        calls = self._calls()
        wrong = []
        for verdict, body in strict_json_corpus():
            if verdict != "REJECT":
                continue
            with patch("requests.sessions.Session.send", _file_reply(200, body, "application/json")):
                for name, call in calls:
                    if self._empty_success(name, body):
                        continue
                    try:
                        _quiet(call)
                    except ZBApiException as error:
                        if error.status_code != 200:
                            wrong.append((name, body, error.status_code))
                    except Exception as error:  # noqa: BLE001 - any other error is a wrong answer too
                        wrong.append((name, body, type(error).__name__))
                    else:
                        wrong.append((name, body, "accepted"))
        self.assertEqual(wrong, [])

    def test_no_json_call_rejects_an_accept_body_as_invalid(self):
        calls = self._calls()
        wrong = []
        for verdict, body in strict_json_corpus():
            if verdict != "ACCEPT":
                continue
            with patch("requests.sessions.Session.send", _file_reply(200, body, "application/json")):
                for name, call in calls:
                    try:
                        _quiet(call)
                    except ZBApiException as error:
                        # A body the client could not parse is the only API error a 2xx without an error field
                        # gives; a result of the wrong shape is a different error.
                        if error.status_code == 200:
                            wrong.append((name, body, str(error)))
                    except Exception:  # noqa: BLE001 - "0" is not a validate result, but it parsed
                        pass
        self.assertEqual(wrong, [])
