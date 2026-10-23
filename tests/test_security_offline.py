"""Security properties: where keys travel, and that they never reach an exception."""

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from requests.exceptions import ConnectionError as RequestsConnectionError

from tests import test_offline_api as offline
from zerobouncesdk import ZBApiException, ZBClientException, ZeroBounce, ZeroBounceWarmup

KEY = "secret-key-123"


class KeyFormatTest(TestCase):
    """A key read from a file keeps its newline; as a header value the HTTP library would quote it unredacted."""

    def test_keys_with_whitespace_or_control_characters_are_rejected_without_echoing_them(self):
        for bad in (KEY + "\n", KEY + "\r\n", " " + KEY, KEY + " ", KEY + "\r\nX-Evil: 1", "ab\tcd", "ab\x7fcd"):
            for client in (ZeroBounce, ZeroBounceWarmup):
                with self.assertRaises(ZBClientException) as caught:
                    client(bad)
                self.assertNotIn(KEY, str(caught.exception))
                self.assertNotIn("ab", str(caught.exception).replace("api_key", ""))

    def test_inner_spaces_are_still_allowed_for_the_validation_api(self):
        ZeroBounce("key with space&plus")


class NoContextLeakTest(TestCase):
    """The redacted error is raised outside the except block, so the original is not its __context__."""

    def setUp(self):
        def refuse(session, request, **kwargs):
            raise RequestsConnectionError(f"failed {request.url} {dict(request.headers)}")

        patcher = patch("requests.sessions.Session.send", refuse)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_transport_errors_carry_no_original(self):
        client = ZeroBounce(KEY)
        warmup = ZeroBounceWarmup(KEY)
        out = str(Path(tempfile.mkdtemp()) / "x.csv")
        calls = [
            client.get_credits,
            lambda: client.validate("a@b.com", use_post=True),
            lambda: client.add_filter("allow", "email", "a@b.com"),
            lambda: client.send_list_evaluator_file_stream(__import__("io").BytesIO(b"a\n"), "l.csv", 1),
            lambda: client.get_file("file-9", out),
            lambda: client.email_finder_get_file("file-9", out),
            client.get_inbox_placement_providers,
            warmup.get_seeds,
            lambda: warmup.test_smtp_configuration("s@example.com", "user", "hunter2-pw", "smtp.example.com", 587),
        ]
        for call in calls:
            with self.assertRaises(RequestsConnectionError) as caught:
                call()
            error = caught.exception
            self.assertIsNone(error.__context__, call)
            self.assertIsNone(error.__cause__, call)
            self.assertNotIn(KEY, str(error), call)
            self.assertNotIn("hunter2-pw", str(error), call)


class TransportPlacementTest(TestCase):
    def setUp(self):
        self.transport = offline.FakeTransport()
        patcher = patch("requests.sessions.Session.send", lambda session, request, **kw: self.transport(request, **kw))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_inbox_placement_key_is_a_bearer_header_never_in_the_url(self):
        client = ZeroBounce(KEY)
        for call in (
            client.get_inbox_placement_providers,
            client.get_inbox_placement_test_types,
            lambda: client.create_inbox_placement_test("Spring launch"),
            lambda: client.get_inbox_placement_test(42),
            client.list_inbox_placement_tests,
            lambda: client.delete_inbox_placement_test(42),
            client.get_inbox_placement_webhook,
            lambda: client.set_inbox_placement_webhook("https://hooks.example.com/ipt"),
        ):
            self.transport.requests.clear()
            call()
            (recorded,) = self.transport.requests
            self.assertEqual(recorded.headers["authorization"], f"Bearer {KEY}")
            self.assertNotIn(KEY, recorded.url)
            self.assertNotIn("api_key", recorded.query)

    def test_non_https_base_urls_never_receive_the_key(self):
        csv = Path(tempfile.mkdtemp()) / "rows.csv"
        csv.write_text("email\na@b.com\n")
        attempts = [
            ("BULK_BASE_URL", lambda c: c.file_status("file-9")),
            ("BULK_BASE_URL", lambda c: c.get_file("file-9", str(csv) + ".out")),
            ("SCORING_BASE_URL", lambda c: c.scoring_send_file(str(csv), 1)),
            ("EMAIL_FINDER_BASE_URL", lambda c: c.email_finder_get_file("file-9", str(csv) + ".f")),
            ("DOMAIN_SEARCH_BASE_URL", lambda c: c.domain_search_file_status("file-9")),
            ("LIST_EVALUATOR_BASE_URL", lambda c: c.get_list_evaluator_result("file-9")),
            ("INBOX_PLACEMENT_BASE_URL", lambda c: c.get_inbox_placement_providers()),
            ("BULK_ROOT_URL", lambda c: c.list_s3files()),
        ]
        for attribute, call in attempts:
            client = ZeroBounce(KEY)
            setattr(client, attribute, "http://bulkapi.zerobounce.net/v2")
            self.transport.requests.clear()
            with self.assertRaises(ZBClientException, msg=attribute):
                call(client)
            self.assertEqual(self.transport.requests, [], attribute)

    def test_dot_segments_are_rejected(self):
        client = ZeroBounce(KEY)
        for call in (
            lambda: client.get_list_evaluator_result(".."),
            lambda: client.get_inbox_placement_test("."),
            lambda: client.delete_inbox_placement_test(".."),
            lambda: ZeroBounceWarmup(KEY).get_custom_engagement(".."),
        ):
            self.transport.requests.clear()
            with self.assertRaises(ZBClientException):
                call()
            self.assertEqual(self.transport.requests, [])


class WarmupBodyRedactionTest(TestCase):
    def test_smtp_secrets_are_masked_in_every_error_path(self):
        warmup = ZeroBounceWarmup(KEY)
        bodies = [
            (200, b"<html><title>login failed for user@example.com / hunter2-pw</title></html>", "text/html"),
            (200, b"login failed for user@example.com with hunter2-pw", "text/plain"),
            (400, json.dumps({"error": "bad password hunter2-pw for user@example.com"}).encode(), "application/json"),
        ]
        for status, body, content_type in bodies:
            with patch(
                "requests.sessions.Session.send",
                lambda session, request, **kw: offline._response(status, body, content_type),
            ):
                try:
                    warmup.test_smtp_configuration("s@example.com", "user@example.com", "hunter2-pw", "smtp.example.com", 587)
                except ZBApiException as error:
                    self.assertNotIn("hunter2-pw", str(error))
                    self.assertNotIn("user@example.com", str(error))
                else:
                    self.fail(f"no error for {status} {content_type}")
