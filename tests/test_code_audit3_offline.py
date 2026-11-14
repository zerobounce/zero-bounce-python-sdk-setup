"""Audit 3 code fixes: strict Warmup dates, success flags, greylist lists, Warmup content warnings, download
targets, and key masking in urllib3 log records."""

import io
import json
import logging
import os
import tempfile
import warnings
from datetime import date, datetime
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

import urllib3.connection
import urllib3.connectionpool

from requests import Response

from zerobouncesdk import ZBApiException, ZBClientException, ZeroBounce, ZeroBounceWarmup
from zerobouncesdk.zb_delete_file_response import ZBDeleteFileResponse
from zerobouncesdk.zb_file_status_response import ZBFileStatusResponse
from zerobouncesdk.zerobouncesdk import _install_log_redaction, _RedactKeyFilter

KEY = "dummy-placeholder-key-0003"
CSV = b"email,status\na@example.com,valid\n"
BOM = b"\xef\xbb\xbf"


def _json(status, body):
    response = Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    response.encoding = "utf-8"
    return response


def _raw(status, body, content_type):
    response = Response()
    response.status_code = status
    response.headers["Content-Type"] = content_type
    response.raw = io.BytesIO(body)
    response.encoding = "utf-8"
    return response


def _answering(body, status=200):
    return patch("requests.sessions.Session.send", lambda s, request, **kw: _json(status, body))


class StrictWarmupDatesTest(TestCase):
    BAD = ("2026-13-01", "2026-02-30", "2026-01-01\n", "٢٠٢٦-٠١-٠١", "2026-00-10", "0000-01-01", "2026-1-1", " 2026-01-01")

    def test_each_bad_date_is_refused_before_sending(self):
        client = ZeroBounceWarmup(KEY)
        with patch("requests.sessions.Session.send") as send:
            for bad in self.BAD:
                with self.subTest(date=bad):
                    with self.assertRaises(ZBClientException):
                        client.get_statistics_per_day("a@example.com", bad, "2026-12-31")
                    with self.assertRaises(ZBClientException):
                        client.get_statistics_per_day("a@example.com", "2026-01-01", bad)
                    with self.assertRaises(ZBClientException):
                        client.add_sending_account(
                            "a@example.com", "zb_managed", managed_sending={"warmup_start_date": bad}
                        )
        send.assert_not_called()

    def test_real_dates_and_date_objects_are_sent(self):
        sent = []

        def send(session, request, **kw):
            sent.append(request.url)
            return _json(200, {})

        client = ZeroBounceWarmup(KEY)
        with patch("requests.sessions.Session.send", send):
            client.get_statistics_per_day("a@example.com", "2024-02-29", date(2026, 3, 1))
            client.get_statistics_per_day("a@example.com", datetime(2026, 1, 1, 13, 5), "2026-12-31")
        self.assertIn("start_date=2024-02-29", sent[0])
        self.assertIn("end_date=2026-03-01", sent[0])
        self.assertIn("start_date=2026-01-01&", sent[1])


class SuccessFlagTest(TestCase):
    def test_one_and_zero_map_to_booleans_as_numbers_and_strings(self):
        self.assertIs(ZBDeleteFileResponse({"success": "1"}).success, True)
        self.assertIs(ZBDeleteFileResponse({"success": 1}).success, True)
        self.assertIs(ZBDeleteFileResponse({"success": 0}).success, False)
        self.assertIs(ZBDeleteFileResponse({"success": "TRUE"}).success, True)

    def test_other_numbers_are_a_wrong_type(self):
        for value in (2, -1, 1.0):
            with self.subTest(value=value):
                with self.assertRaises(ZBApiException) as caught:
                    with _answering({"success": value, "file_id": "f"}):
                        ZeroBounce(KEY).delete_file("f")
                self.assertIn("success", str(caught.exception))
                self.assertEqual(caught.exception.status_code, 200)

    def test_a_numeric_success_is_a_result_on_a_file_call(self):
        with _answering({"success": 1, "file_name": "n", "file_id": "f", "message": "ok"}):
            self.assertIs(ZeroBounce(KEY).delete_file("f").success, True)

    def test_a_missing_success_reads_false_as_in_java(self):
        self.assertIs(ZBFileStatusResponse({"file_id": "f"}).success, False)

    def test_a_non_boolean_success_on_a_call_without_that_field_is_ignored_as_in_java(self):
        with _answering({"Credits": 5, "success": "no"}):
            self.assertEqual(ZeroBounce(KEY).get_credits().credits, 5)


class GreylistListTest(TestCase):
    def test_a_list_message_is_a_message_error_not_a_missing_address(self):
        with _answering({"Message": ["Invalid API key", "or no credits"]}):
            with self.assertRaises(ZBApiException) as caught:
                ZeroBounce(KEY).validate("a@example.com")
        self.assertEqual(str(caught.exception), "Invalid API key\nor no credits")
        self.assertEqual(caught.exception.status_code, 200)

    def test_a_string_greylist_message_is_still_a_result(self):
        with _answering({"Message": "Greylist validation started"}):
            ZeroBounce(KEY).validate("a@example.com")  # does not raise ZBApiException


class WarmupContentTest(TestCase):
    def _add(self, content):
        sent = []

        def send(session, request, **kw):
            sent.append(json.loads(request.body))
            return _json(200, {})

        with patch("requests.sessions.Session.send", send):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                ZeroBounceWarmup(KEY).add_sending_account("a@example.com", "zb_managed", email_content=content)
        return sent, caught

    def test_website_is_deprecated(self):
        sent, caught = self._add({"website": "https://example.com"})
        self.assertEqual(sent[0]["email_content"]["company_website"], "https://example.com")
        self.assertTrue(any(issubclass(w.category, DeprecationWarning) and "website" in str(w.message) for w in caught))

    def test_a_dropped_website_warns(self):
        sent, caught = self._add({"website": "https://a.example", "company_website": "https://b.example"})
        self.assertEqual(sent[0]["email_content"]["company_website"], "https://b.example")
        self.assertTrue(any("ignored" in str(w.message) for w in caught))

    def test_an_empty_types_list_warns(self):
        sent, caught = self._add({"types_of_emails": [], "company_name": "x"})
        self.assertNotIn("types_of_emails", sent[0]["email_content"])
        self.assertTrue(any("types_of_emails is empty" in str(w.message) for w in caught))

    def test_blank_text_is_refused(self):
        client = ZeroBounceWarmup(KEY)
        with patch("requests.sessions.Session.send") as send:
            for key in ("company_name", "company_website", "company_description", "example_email"):
                with self.subTest(key=key):
                    with self.assertRaises(ZBClientException):
                        client.add_sending_account("a@example.com", "zb_managed", email_content={key: "  "})
        send.assert_not_called()


class _Downloads(TestCase):
    def setUp(self):
        self.sent = []
        self.reply = (200, CSV, "text/csv")

        def send(session, request, **kwargs):
            self.sent.append(request.url)
            return _raw(*self.reply)

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


class DownloadTargetTest(_Downloads):
    @skipUnless(hasattr(os, "geteuid") and os.geteuid() != 0, "root ignores folder permissions")
    def test_a_relative_path_in_a_read_only_cwd_is_refused_before_sending(self):
        locked = self.folder / "cwd"
        locked.mkdir()
        os.chmod(locked, 0o500)
        self.addCleanup(os.chmod, locked, 0o700)
        old = os.getcwd()
        os.chdir(locked)
        self.addCleanup(os.chdir, old)
        for name, call in self.downloads():
            with self.subTest(call=name):
                with self.assertRaises(ZBClientException) as caught:
                    call(os.path.join("new", "out.csv"))
                self.assertIn("permission denied", str(caught.exception))
        self.assertEqual(self.sent, [])

    def test_a_file_as_a_path_component_is_refused_before_sending(self):
        (self.folder / "afile").write_text("x")
        for name, call in self.downloads():
            for rest in ("out.csv", os.path.join("deeper", "out.csv")):
                with self.subTest(call=name, rest=rest):
                    with self.assertRaises(ZBClientException) as caught:
                        call(str(self.folder / "afile" / rest))
                    self.assertIn("is a file", str(caught.exception))
        self.assertEqual(self.sent, [])

    def test_a_dangling_link_is_written_through_to_its_missing_target(self):
        for name, call in self.downloads():
            with self.subTest(call=name):
                target = self.folder / f"{name}-target.csv"
                link = self.folder / f"{name}-dangling.csv"
                os.symlink(target, link)
                call(str(link))
                self.assertTrue(link.is_symlink())
                self.assertEqual(target.read_bytes(), CSV)

    @skipUnless(hasattr(os, "geteuid") and os.geteuid() != 0, "root ignores folder permissions")
    def test_a_folder_with_write_but_no_execute_is_refused(self):
        locked = self.folder / "noexec"
        locked.mkdir()
        os.chmod(locked, 0o600)
        self.addCleanup(os.chmod, locked, 0o700)
        for name, call in self.downloads():
            with self.subTest(call=name):
                with self.assertRaises(ZBClientException) as caught:
                    call(str(locked / "out.csv"))
                self.assertIn("permission denied", str(caught.exception))
        self.assertEqual(self.sent, [])

    def test_a_bom_only_plain_and_warmup_download_is_an_empty_response(self):
        self.reply = (200, BOM, "text/csv")
        for name, call in self.downloads():
            if name == "stream":
                continue
            with self.subTest(call=name):
                path = self.folder / f"{name}-bom.csv"
                with self.assertRaises(ZBApiException) as caught:
                    call(str(path))
                self.assertIn("Empty response", str(caught.exception))
                self.assertFalse(path.exists())


class _Records(TestCase):
    def setUp(self):
        self.clients = [ZeroBounce(KEY), ZeroBounceWarmup("warmup-dummy-key-0003")]
        _install_log_redaction()
        self.stream = io.StringIO()
        handler = logging.StreamHandler(self.stream)
        handler.setLevel(logging.WARNING)
        root = logging.getLogger()
        root.addHandler(handler)
        self.addCleanup(root.removeHandler, handler)

    def emit(self, name, text, *args, **kwargs):
        logging.getLogger(name).warning(text, *args, **kwargs)
        return self.stream.getvalue()


class LogMaskingTest(_Records):
    LEAKS = (
        "https://x/y?api%5Fkey=SECRETVALUE",
        "https://x/y?api_key%253DSECRETVALUE",
        '{"api_key": "SECRETVALUE"}',
        "x_api_key=SECRETVALUE",
        "API-Key: SECRETVALUE",
        "https://x/v2/SECRETVALUE/getcredits",
    )

    def test_the_parameter_name_forms_are_masked(self):
        for text in ("?api_key=PLAINVALUE&x", "?api_key%3DPLAINVALUE", "?API_KEY=PLAINVALUE", "?ApiKey=PLAINVALUE"):
            with self.subTest(text=text):
                out = self.emit("urllib3.connectionpool", text)
                self.assertNotIn("PLAINVALUE", out)

    def test_a_configured_key_is_masked_by_value_wherever_it_appears(self):
        for key in (KEY, "warmup-dummy-key-0003"):
            for template in ("https://x/y?api%5Fkey={k}", "https://x/y?api_key%253D{k}", '{{"api_key": "{k}"}}',
                             "x_api_key={k}", "API-Key: {k}", "https://x/v2/{k}/getcredits", "it's {k}'s"):
                with self.subTest(key=key, template=template):
                    out = self.emit("urllib3.connectionpool", template.format(k=key))
                    self.assertNotIn(key, out)

    def test_every_urllib3_logger_is_covered(self):
        # Loggers that exist when a request is sent are covered: every send re-installs the filter
        # (_check_transport_logging), including on loggers created since the last send.
        for name in ("urllib3", "urllib3.poolmanager", "urllib3.connectionpool", "urllib3.util.retry",
                     "urllib3.contrib.pyopenssl", "urllib3.some.child"):
            with self.subTest(logger=name):
                logging.getLogger(name)
                _install_log_redaction()
                self.assertNotIn(KEY, self.emit(name, "retry %s", f"https://x/y?api_key={KEY}"))

    def test_the_sdk_does_not_replace_the_global_log_record_factory(self):
        before = logging.getLogRecordFactory()
        _install_log_redaction()
        self.assertIs(logging.getLogRecordFactory(), before)

    def test_exception_and_stack_text_are_masked_and_the_record_is_kept(self):
        records = []

        class Keep(logging.Handler):
            def emit(self, record):
                records.append(record)

        keep = Keep()
        logging.getLogger().addHandler(keep)
        self.addCleanup(logging.getLogger().removeHandler, keep)
        try:
            raise ValueError(f"failed https://x/y?api_key={KEY}")
        except ValueError:
            logging.getLogger("urllib3.connectionpool").warning("retrying", exc_info=True, stack_info=True)
        out = self.stream.getvalue()
        self.assertIn("ValueError", out)
        self.assertNotIn(KEY, out)
        self.assertEqual(len(records), 1)
        self.assertNotIn(KEY, records[0].exc_text)
        self.assertNotIn(KEY, records[0].stack_info or "")

    def test_a_filter_removed_from_a_logger_is_reinstalled_on_the_next_send(self):
        logger = logging.getLogger("urllib3.poolmanager")
        for f in [f for f in logger.filters if isinstance(f, _RedactKeyFilter)]:
            logger.removeFilter(f)
        with _answering({"Credits": 1}):
            self.clients[0].get_credits()
        self.assertTrue(any(isinstance(f, _RedactKeyFilter) for f in logger.filters))


class DebugHolderTest(TestCase):
    def _refused(self):
        with patch("requests.sessions.Session.send") as send:
            with self.assertRaises(ZBClientException) as caught:
                ZeroBounce(KEY).get_credits()
        send.assert_not_called()
        return str(caught.exception)

    def test_a_pools_connection_class_with_debuglevel_blocks_the_send(self):
        for pool in (urllib3.connectionpool.HTTPConnectionPool, urllib3.connectionpool.HTTPSConnectionPool):
            with self.subTest(pool=pool.__name__):
                custom = type("Custom", (pool.ConnectionCls,), {"debuglevel": 1})
                with patch.object(pool, "ConnectionCls", custom):
                    self.assertIn(f"{pool.__name__}.ConnectionCls", self._refused())

    def test_the_urllib3_https_connection_with_debuglevel_blocks_the_send(self):
        with patch.object(urllib3.connection.HTTPSConnection, "debuglevel", 1, create=True):
            self.assertIn("urllib3.connection.HTTPSConnection", self._refused())

    def test_the_failure_text_names_the_logger_that_is_enabled(self):
        for name in ("requests", "http.client"):
            with self.subTest(logger=name):
                logger = logging.getLogger(name)
                before = logger.level
                self.addCleanup(logger.setLevel, before)
                logger.setLevel(logging.DEBUG)
                message = self._refused()
                self.assertIn(f"the {name} logger", message)
                self.assertNotIn("urllib3 logger", message)
                logger.setLevel(before)
