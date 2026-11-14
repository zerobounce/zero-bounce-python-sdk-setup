"""Download and transport fixes: JSON bodies, file modes, symlinks, bad targets, timeouts."""

import os
import stat
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from requests import Response

from zerobouncesdk import ZBApiException, ZBClientException, ZeroBounce
from zerobouncesdk.zb_warmup import ZeroBounceWarmup

KEY = "secret-key-123"
CSV = b"email,status\na@example.com,valid\n"
BOM = b"\xef\xbb\xbf"


def _response(status, body, content_type):
    import io

    response = Response()
    response.status_code = status
    response.headers["Content-Type"] = content_type
    response.raw = io.BytesIO(body)
    response.encoding = "utf-8"
    return response


class _Base(TestCase):
    def setUp(self):
        self.sent = []
        self.reply = (200, CSV, "text/csv")

        def send(session, request, **kwargs):
            self.sent.append(kwargs)
            return _response(*self.reply)

        patcher = patch("requests.sessions.Session.send", send)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = Path(tempfile.mkdtemp())
        self.client = ZeroBounce(KEY)
        self.warmup = ZeroBounceWarmup(KEY)

    def downloads(self):
        yield "plain", lambda p: self.client.get_file("f1", p)
        yield "stream", lambda p: self.client.get_file("f1", p, stream=True)
        yield "warmup", lambda p: self.warmup.download_seeds(p)


class JsonBodyIsAnErrorTest(_Base):
    def test_json_shaped_bodies_are_errors_and_save_nothing(self):
        cases = [
            (BOM + b'{"success":false,"message":"bad"}', "text/csv"),
            (b'[{"error":"bad"}]', "text/csv"),
            (BOM + b'[{"error":"bad"}]', "application/octet-stream"),
            (b'{"detail":"bad"}', "text/csv"),
            (b'{"title":"bad"}', "application/problem+json"),
            (CSV, "application/problem+json"),
            (CSV, "application/vnd.api+json; charset=utf-8"),
        ]
        for body, content_type in cases:
            for name, call in self.downloads():
                with self.subTest(body=body, content_type=content_type, call=name):
                    self.reply = (200, body, content_type)
                    path = self.folder / "out.csv"
                    with self.assertRaises(ZBApiException) as caught:
                        call(str(path))
                    self.assertEqual(caught.exception.status_code, 200)
                    self.assertEqual(list(self.folder.iterdir()), [])

    def test_a_csv_that_is_not_json_is_still_saved(self):
        for body in (CSV, BOM + CSV, b"[x] done,valid\n"):
            for name, call in self.downloads():
                with self.subTest(body=body, call=name):
                    self.reply = (200, body, "text/csv")
                    path = self.folder / f"{name}.csv"
                    call(str(path))
                    self.assertEqual(path.read_bytes(), body)


class TargetTest(_Base):
    def test_bad_targets_are_refused_before_sending_and_create_nothing(self):
        (self.folder / "dir").mkdir()
        os.symlink(self.folder / "missing" / "x.csv", self.folder / "dangling.csv")
        os.symlink(self.folder / "dir", self.folder / "dirlink")
        before = sorted(os.listdir(self.folder))
        for target in ("", "   ", str(self.folder / "sub") + "/", str(self.folder / "dir"),
                       str(self.folder / "dangling.csv"), str(self.folder / "dirlink")):
            for name, call in self.downloads():
                with self.subTest(target=target, call=name):
                    self.sent.clear()
                    with self.assertRaises(ZBClientException):
                        call(target)
                    self.assertEqual(self.sent, [])
        self.assertEqual(sorted(os.listdir(self.folder)), before)
        self.assertFalse((self.folder / "missing").exists())

    def test_an_existing_file_keeps_its_permissions(self):
        for name, call in self.downloads():
            with self.subTest(call=name):
                path = self.folder / f"{name}.csv"
                path.write_bytes(b"old")
                os.chmod(path, 0o600)
                old_umask = os.umask(0o000)
                try:
                    call(str(path))
                finally:
                    os.umask(old_umask)
                self.assertEqual(path.read_bytes(), CSV)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_a_symlink_is_written_through_and_kept(self):
        for name, call in self.downloads():
            with self.subTest(call=name):
                real = self.folder / f"{name}-real.csv"
                real.write_bytes(b"old")
                link = self.folder / f"{name}-link.csv"
                os.symlink(real, link)
                call(str(link))
                self.assertTrue(link.is_symlink())
                self.assertEqual(real.read_bytes(), CSV)

    def test_a_failed_download_removes_the_directories_it_made(self):
        self.reply = (200, b'{"success":false,"message":"bad"}', "text/csv")
        for name, call in self.downloads():
            with self.assertRaises(ZBApiException):
                call(str(self.folder / name / "deep" / "out.csv"))
            self.assertFalse((self.folder / name).exists())


class TimeoutTest(_Base):
    def test_default_is_a_connect_read_pair(self):
        with self.assertRaises(Exception):
            self.client.get_credits()
        self.assertEqual(self.sent[-1]["timeout"], (30.0, 120.0))
        self.sent.clear()
        with self.assertRaises(Exception):
            self.warmup.list_sending_accounts()
        self.assertEqual(self.sent[-1]["timeout"], (30.0, 120.0))


class TransportRound2Test(_Base):
    def _cut_stream(self):
        from requests.exceptions import ChunkedEncodingError

        def iter_content(self_, chunk_size=1, decode_unicode=False):
            yield b"email,status\n" + b"a@example.com,valid\n" * 5000  # past the 64 KiB sniff window
            yield b"b" * (70 * 1024)
            raise ChunkedEncodingError("cut")

        return patch("requests.Response.iter_content", iter_content)

    def test_a_download_cut_after_the_folders_exist_removes_them(self):
        with self._cut_stream():
            from requests.exceptions import ChunkedEncodingError

            with self.assertRaises(ChunkedEncodingError):
                self.client.get_file("f1", str(self.folder / "m1" / "m2" / "out.csv"), stream=True)
        self.assertFalse((self.folder / "m1").exists())

    def test_a_bom_only_stream_is_an_empty_response(self):
        self.reply = (200, BOM, "text/csv")
        path = self.folder / "bom.csv"
        with self.assertRaises(ZBApiException) as caught:
            self.client.get_file("f1", str(path), stream=True)
        self.assertIn("Empty response", str(caught.exception))
        self.assertFalse(path.exists())

    def test_a_new_file_gets_the_umask_mode_not_0600(self):
        old = os.umask(0o022)
        try:
            for name, call in self.downloads():
                path = self.folder / f"{name}-new.csv"
                call(str(path))
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644, name)
        finally:
            os.umask(old)

    def test_a_read_only_folder_is_refused_before_sending(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores folder permissions")
        locked = self.folder / "locked"
        locked.mkdir()
        os.chmod(locked, 0o500)
        self.addCleanup(os.chmod, locked, 0o700)
        for name, call in self.downloads():
            with self.subTest(call=name):
                with self.assertRaises(ZBClientException) as caught:
                    call(str(locked / "sub" / "out.csv"))
                self.assertIn("permission denied", str(caught.exception))
                self.assertIn(str(locked), str(caught.exception))
                self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(self.sent, [])

    def test_a_write_failure_after_the_request_is_a_client_exception(self):
        for name, call in self.downloads():
            with self.subTest(call=name):
                path = self.folder / f"{name}-w.csv"
                with patch("zerobouncesdk.zerobouncesdk.os.replace", side_effect=PermissionError(13, "Permission denied")):
                    with self.assertRaises(ZBClientException) as caught:
                        call(str(path))
                self.assertIn(str(path), str(caught.exception))
                self.assertIn("Permission denied", str(caught.exception))
                self.assertNotIn(KEY, str(caught.exception))

    def test_a_link_to_a_directory_names_the_link_problem(self):
        folder = self.folder / "dir"
        folder.mkdir()
        link = self.folder / "dirlink"
        os.symlink(folder, link)
        with self.assertRaises(ZBClientException) as caught:
            self.client.get_file("f1", str(link))
        self.assertIn("link to a directory", str(caught.exception))

    def test_a_self_referencing_link_is_refused_before_sending(self):
        loop = self.folder / "loop"
        os.symlink(loop, loop)
        for name, call in self.downloads():
            with self.subTest(call=name):
                with self.assertRaises(ZBClientException) as caught:
                    call(str(loop))
                self.assertIn("loops", str(caught.exception))
        self.assertTrue(loop.is_symlink())
        self.assertEqual(self.sent, [])
