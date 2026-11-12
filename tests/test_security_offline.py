"""Security properties: where keys travel, and that they never reach an exception."""

import json
import tempfile
from itertools import product
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from requests.exceptions import ConnectionError as RequestsConnectionError

from tests import test_offline_api as offline
from zerobouncesdk import ZBApiException, ZBClientException, ZeroBounce, ZeroBounceWarmup
from zerobouncesdk.zerobouncesdk import _redact_secrets

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


# A secret with the characters each encoding changes: JSON escapes '"' (and may escape '/'), URLs encode all four.
ODD_KEY = 'odd"key/with+plus%25'
ODD_PASSWORD = 'pw"with/slash+plus%41'


def _echo_forms(secret):
    """The secret as a server or proxy can echo it: raw, URL-encoded, and JSON-escaped (with and without '\\/')."""
    from urllib.parse import quote, quote_plus

    escaped = json.dumps(secret)[1:-1]
    return [secret, quote_plus(secret), quote(secret, safe=""), escaped, escaped.replace("/", "\\/")]


def _echo_bodies(secret):
    """Bodies that quote the secret in each form; JSON bodies are written by hand so the escaping is the server's."""
    for form in _echo_forms(secret):
        yield 400, f'{{"error": "Invalid API key {form}"}}'.encode(), "application/json"
        yield 200, f'{{"error": "Invalid API key {form}"}}'.encode(), "application/json"
        yield 200, f'{{"success": false, "message": "rejected {form}"}}'.encode(), "application/json"
        yield 500, f"upstream failed for ?api_key={form}".encode(), "text/plain"


def _leaks(text, secret):
    return [form for form in _echo_forms(secret) if form in text]


class JsonEscapedSecretTest(TestCase):
    """S4/S7: a secret quoted in a body is masked in every form, on every request method."""

    def _sweep(self, calls, secret):
        from tests.test_transport_guards_offline import _quiet

        leaks = []
        for status, body, content_type in _echo_bodies(secret):
            with patch(
                "requests.sessions.Session.send",
                lambda session, request, **kw: offline._response(status, body, content_type),
            ):
                for name, call in calls:
                    try:
                        _quiet(call)
                    except Exception as error:  # noqa: BLE001 - every error is inspected
                        seen = f"{error}|{error!r}|{error.args!r}|{error.__context__!r}|{error.__cause__!r}"
                        found = _leaks(seen, secret)
                        if found:
                            leaks.append((name, status, found))
        return leaks

    def test_the_client_masks_its_key_in_every_form(self):
        from tests.test_transport_guards_offline import client_calls

        client = ZeroBounce(ODD_KEY)
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        calls = [(name, call) for name, variants in client_calls(client, out).items() for call in variants]
        self.assertEqual(self._sweep(calls, ODD_KEY), [])

    def test_the_warmup_client_masks_its_key_in_every_form(self):
        from tests.test_transport_guards_offline import warmup_calls

        warmup = ZeroBounceWarmup(ODD_KEY)
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        calls = [(name, lambda c=call: c(warmup)) for name, call in warmup_calls(out).items()]
        self.assertEqual(self._sweep(calls, ODD_KEY), [])

    def test_smtp_secrets_are_masked_in_every_form(self):
        warmup = ZeroBounceWarmup(KEY)
        for secret, call in (
            (ODD_PASSWORD, lambda: warmup.test_smtp_configuration("s@example.com", "user", ODD_PASSWORD, "smtp.example.com", 587)),
            (ODD_PASSWORD, lambda: warmup.test_smtp_configuration("s@example.com", ODD_PASSWORD, "pw", "smtp.example.com", 587)),
        ):
            self.assertEqual(self._sweep([("test_smtp_configuration", call)], secret), [])


class EverySpellingTest(TestCase):
    """S4/S7: each spelling of a secret, composed here from the encoders themselves, is masked.

    {raw, JSON, JSON with \\/} (each JSON form with non-ASCII escaped or as is) x {as is, URL-encoded with +,
    with %20, with / kept}, each JSON form escaped twice, and repr. The first secret holds every character an
    encoding changes; the second a non-ASCII character next to a space, '/' and '"'. Each spelling has a value
    no other spelling has for one of them, so dropping any one generator from ``_secret_forms`` fails.
    """

    SECRETS = ("a b\"/+%&=<>'\\", 'pw\u00e9 /"x')

    @staticmethod
    def spellings(secret):
        from urllib.parse import quote, quote_plus

        def as_json(text, ensure_ascii, slash):
            escaped = json.dumps(text, ensure_ascii=ensure_ascii)[1:-1]
            return escaped.replace("/", "\\/") if slash else escaped

        escapers = {"raw": lambda text: text}
        for ensure_ascii, slash in product((True, False), (False, True)):
            label = "JSON" + (" \\/" if slash else "") + ("" if ensure_ascii else ", non-ASCII as is")
            escapers[label] = lambda text, a=ensure_ascii, sl=slash: as_json(text, a, sl)
        url_encoders = {
            "": lambda text: text,
            ", URL-encoded +": quote_plus,
            ", URL-encoded %20": lambda text: quote(text, safe=""),
            ", URL-encoded / kept": quote,
        }
        spellings = {"repr": repr(secret)[1:-1]}
        for (escape_label, escape), (url_label, encode) in product(escapers.items(), url_encoders.items()):
            spellings[escape_label + url_label] = encode(escape(secret))
        for escape_label, escape in escapers.items():
            if escape_label != "raw":
                spellings[escape_label + ", twice"] = escape(escape(secret))
        return spellings

    def test_the_spellings_are_composed(self):
        self.assertEqual(len(self.spellings(self.SECRETS[0])), 1 + 5 * 4 + 4)

    def test_each_spelling_is_masked_whole(self):
        for secret in self.SECRETS:
            for label, form in self.spellings(secret).items():
                self.assertEqual(_redact_secrets(f"<{form}>", [secret]), "<***>", label)

    def test_each_spelling_is_needed_by_one_secret(self):
        shared = [
            label
            for label in self.spellings(self.SECRETS[0])
            if all(list(self.spellings(s).values()).count(self.spellings(s)[label]) > 1 for s in self.SECRETS)
        ]
        self.assertEqual(shared, [])

    def test_each_spelling_is_masked_as_the_key_and_as_the_smtp_password(self):
        leaks = []
        for secret in self.SECRETS:
            for label, form in self.spellings(secret).items():
                # Plain text is quoted unless it holds "<>{}[]"; an HTML page by its title.
                bodies = (
                    (400, f"rejected: {form}".encode(), "text/plain"),
                    (200, f"<html><head><title>rejected {form}</title></head></html>".encode(), "text/html"),
                )
                calls = {
                    "key": lambda s=secret: ZeroBounce(s).get_credits(),
                    "password": lambda s=secret: ZeroBounceWarmup(KEY).test_smtp_configuration(
                        "a@example.com", "smtp-user-1", s, "smtp.example.com", 587
                    ),
                }
                for (status, body, content_type), (what, call) in product(bodies, calls.items()):
                    with patch(
                        "requests.sessions.Session.send",
                        lambda session, request, **kw: offline._response(status, body, content_type),
                    ):
                        with self.assertRaises(ZBApiException, msg=f"{what} {label}") as caught:
                            call()
                    error = caught.exception
                    if form in f"{error}|{error!r}|{error.args!r}|{error.__context__!r}":
                        leaks.append((what, label, status, secret))
        self.assertEqual(leaks, [])


class PicklingTest(TestCase):
    """S6: a pickle of a client would carry its key to wherever the pickle is written, so it is refused."""

    def test_clients_refuse_to_be_pickled(self):
        import copy
        import pickle

        for client in (ZeroBounce(KEY), ZeroBounceWarmup(KEY)):
            for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError, msg=f"{type(client).__name__} protocol {protocol}") as caught:
                    pickle.dumps(client, protocol)
                self.assertNotIn(KEY, str(caught.exception))
            for clone in (copy.copy, copy.deepcopy):
                with self.assertRaises(TypeError):
                    clone(client)
