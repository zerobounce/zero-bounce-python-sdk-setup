"""Security audit 1 (Python): case-insensitive and entity redaction, key characters, base URLs, DEBUG-logging guard."""

import http.client
import logging
from unittest import TestCase
from unittest.mock import patch

from tests import test_offline_api as offline
from zerobouncesdk import ZBApiException, ZBClientException, ZeroBounce, ZeroBounceWarmup
from zerobouncesdk.zerobouncesdk import CREDENTIAL_OMITTED_MESSAGE, _redact_secrets

KEY = "dummy-placeholder-key-0001"


def _sent_back(body, status=400, content_type="text/plain"):
    return patch("requests.sessions.Session.send", lambda s, request, **kw: offline._response(status, body, content_type))


def _keyed(cls, secret):
    client = cls("dummy-placeholder-key")
    client._api_key.value = secret
    return client


class CaseInsensitiveRedactionTest(TestCase):
    def test_an_upper_cased_or_lower_cased_echo_is_masked(self):
        secret = "AbCd-Key-123"
        for echo in (secret.upper(), secret.lower(), secret.swapcase()):
            self.assertEqual(_redact_secrets(f"bad key {echo}!", [secret]), "bad key ***!", echo)

    def test_an_upper_cased_key_echo_never_reaches_the_error_main_client(self):
        with _sent_back(f"Invalid key {KEY.upper()}".encode()):
            with self.assertRaises(ZBApiException) as caught:
                ZeroBounce(KEY).get_credits()
        self.assertNotIn(KEY.upper(), f"{caught.exception}|{caught.exception!r}")
        self.assertNotIn(KEY.upper().lower(), f"{caught.exception}".lower())

    def test_an_upper_cased_key_echo_never_reaches_the_error_warmup_client(self):
        with _sent_back(f"Invalid key {KEY.upper()}".encode()):
            with self.assertRaises(ZBApiException) as caught:
                ZeroBounceWarmup(KEY).get_seeds()
        self.assertNotIn(KEY.lower(), f"{caught.exception}|{caught.exception!r}".lower())

    def test_an_upper_cased_smtp_password_echo_is_masked(self):
        password = "smtp-Pass-word-9"
        with _sent_back(f"login failed for {password.upper()}".encode(), 500):
            with self.assertRaises(ZBApiException) as caught:
                ZeroBounceWarmup(KEY).test_smtp_configuration("a@example.com", "smtp-user", password, "smtp.example.com", 587)
        self.assertNotIn(password.lower(), f"{caught.exception}|{caught.exception!r}".lower())

    def test_a_percent_encoded_echo_in_other_letter_case_is_masked(self):
        self.assertNotIn("zz", _redact_secrets("x=%2fZZ%2F", ["/zz/"]).lower().replace("***", ""))


class MarkupEchoRedactionTest(TestCase):
    SECRET = "a'b\"c&d<e>f"

    def test_entity_and_backslash_spellings_are_masked(self):
        spellings = (
            "a&#39;b&quot;c&amp;d&lt;e&gt;f",
            "a&#x27;b&#x22;c&#x26;d&#x3c;e&#x3e;f",
            "a&#X27;b&QUOT;c&AMP;d&LT;e&GT;f",
            "a&apos;b&quot;c&amp;d&lt;e&gt;f",
            "a\\'b\\\"c&d<e>f",
        )
        for text in spellings:
            redacted = _redact_secrets(f"<p>{text}</p>", [self.SECRET])
            self.assertIn(redacted, ("<p>***</p>", CREDENTIAL_OMITTED_MESSAGE), text)
            self.assertNotIn("b", redacted.replace("<p>", "").replace("</p>", "").replace("***", ""), text)

    def test_a_mixed_spelling_is_omitted(self):
        redacted = _redact_secrets("a&#39;b&quot;c&amp;d<e&gt;f", [self.SECRET])
        self.assertIn(redacted, ("***", CREDENTIAL_OMITTED_MESSAGE))
        self.assertNotIn("a&#39;", redacted)

    def test_a_double_entity_echo_is_omitted(self):
        self.assertEqual(_redact_secrets("x a&amp;#39;b y", ["a'b"]), CREDENTIAL_OMITTED_MESSAGE)


class ApiKeyCharactersTest(TestCase):
    CHARACTERS = {
        "ZWSP": "​",
        "BOM": "﻿",
        "MONGOLIAN VOWEL SEPARATOR": "᠎",
        "LINE SEPARATOR": " ",
        "NEL": "\u0085",
        "NBSP": " ",
        "word joiner": "⁠",
        "space": " ",
        "tab": "\t",
        "DEL": "\x7f",
    }

    def test_whitespace_control_and_format_characters_are_refused_anywhere(self):
        for label, char in self.CHARACTERS.items():
            for key in (f"dummy{char}key", f"{char}dummykey", f"dummykey{char}"):
                for build in (ZeroBounce, ZeroBounceWarmup):
                    with self.assertRaises(ZBClientException, msg=f"{build.__name__} {label}") as caught:
                        build(key)
                    self.assertEqual(str(caught.exception), "api_key has whitespace, control or invisible characters")

    def test_non_ascii_is_refused_with_the_header_message(self):
        for key in ("dummyékey", "dummy中key", "dummy\U0001F600key", "dummy\ud800key"):
            for build in (ZeroBounce, ZeroBounceWarmup):
                with self.assertRaises(ZBClientException) as caught:
                    build(key)
                self.assertEqual(str(caught.exception), "api_key has characters that cannot be sent in an HTTP header")
                self.assertNotIn("dummy", str(caught.exception))

    def test_a_printable_ascii_key_is_accepted(self):
        ZeroBounce("dummy-KEY_0123456789.~!#$%&'*+/=?^`{|}")
        ZeroBounceWarmup("dummy-KEY_0123456789")

    def test_a_unicode_encode_error_never_escapes(self):
        for build, call in (
            (ZeroBounce, lambda c: c.get_credits()),
            (ZeroBounceWarmup, lambda c: c.get_seeds()),
        ):
            client = build(KEY)
            client._api_key.value = "dummyékey"  # as if set after the constructor's check
            error = UnicodeEncodeError("latin-1", client._api_key.value, 5, 6, "ordinal not in range")
            with patch("requests.sessions.Session.send", side_effect=error):
                with self.assertRaises(ZBClientException) as caught:
                    call(client)
            self.assertNotIn("dummy", f"{caught.exception}|{caught.exception!r}")
            self.assertIsNone(caught.exception.__context__)


class BaseUrlTest(TestCase):
    BAD = (
        "https://api.zerobounce.net@evil.example/v2",
        "https://user:pw@api.zerobounce.net/v2",
        "https://exa mple.com",
        "https://example.com/v 2",
        "https://",
        "https:///v2",
        "https://example.com\n/v2",
        "https://example.com/v2\n",
        "https://example.com\t",
        "https://[::1/v2",
        "https://example.com:99999/v2",
        "https://example.com:abc/v2",
        "https://example.com:0/v2",
        "https://example.com:/v2",
        "https://exam\\ple.com/v2",
        "https://evil.example\\@api.zerobounce.net/v2",
        "https://-bad-.example/v2",
        "https://exa..mple.com/v2",
        "https://exam​ple.com/v2",
        "http://api.zerobounce.net/v2",
        "ftp://api.zerobounce.net/v2",
    )
    GOOD = (
        "https://api.zerobounce.net/v2",
        "https://api-eu.zerobounce.net/v2/",
        "HTTPS://Example.com:8443/v2",
        "https://127.0.0.1:8443",
        "https://[::1]:8443/v2",
    )

    def test_both_clients_refuse_a_bad_base_url(self):
        for url in self.BAD:
            for build in (ZeroBounce, ZeroBounceWarmup):
                with self.assertRaises(ZBClientException, msg=f"{build.__name__} {url!r}"):
                    build(KEY, url)

    def test_both_clients_accept_a_good_base_url(self):
        for url in self.GOOD:
            ZeroBounce(KEY, url)
            ZeroBounceWarmup(KEY, url)

    def test_a_reassigned_base_url_is_checked_on_every_send(self):
        for url in self.BAD:
            client = ZeroBounce(KEY)
            client._base_url = url
            client.BULK_BASE_URL = url
            with patch("requests.sessions.Session.send") as send:
                with self.assertRaises(ZBClientException, msg=repr(url)):
                    client.get_credits()
                with self.assertRaises(ZBClientException, msg=repr(url)):
                    client.file_status("f1")
            send.assert_not_called()

    def test_a_reassigned_warmup_root_is_checked_on_every_send(self):
        for url in self.BAD + ("http://example.com",):
            warmup = ZeroBounceWarmup(KEY)
            warmup._root = url + warmup.BASE_PATH
            with patch("requests.sessions.Session.send") as send:
                with self.assertRaises(ZBClientException, msg=repr(url)):
                    warmup.get_seeds()
            send.assert_not_called()


class DebugLoggingGuardTest(TestCase):
    LOGGERS = ("urllib3", "urllib3.connectionpool", "urllib3.util.retry")

    def _refused(self, sent_text="ok"):
        with patch("requests.sessions.Session.send") as send:
            with self.assertRaises(ZBClientException) as caught:
                ZeroBounce(KEY).get_credits()
            with self.assertRaises(ZBClientException):
                ZeroBounceWarmup(KEY).get_seeds()
        send.assert_not_called()
        self.assertNotIn(KEY, str(caught.exception))
        return str(caught.exception)

    def test_a_debug_urllib3_logger_blocks_every_send(self):
        for name in self.LOGGERS:
            logger = logging.getLogger(name)
            before = logger.level
            self.addCleanup(logger.setLevel, before)
            logger.setLevel(logging.DEBUG)
            message = self._refused()
            self.assertIn("debug logging", message)
            self.assertIn(name, message)
            logger.setLevel(before)

    def test_a_root_logger_at_debug_blocks_the_send(self):
        root = logging.getLogger()
        before = root.level
        self.addCleanup(root.setLevel, before)
        root.setLevel(logging.DEBUG)
        self._refused()

    def test_http_client_debuglevel_blocks_the_send(self):
        self.addCleanup(setattr, http.client.HTTPConnection, "debuglevel", http.client.HTTPConnection.debuglevel)
        http.client.HTTPConnection.debuglevel = 1
        self.assertIn("debuglevel", self._refused())

    def test_the_key_is_not_logged_with_the_guard_in_place(self):
        logger = logging.getLogger("urllib3.connectionpool")
        self.addCleanup(logger.setLevel, logger.level)
        logger.setLevel(logging.DEBUG)
        with self.assertNoLogs("urllib3", logging.DEBUG):
            with patch("requests.sessions.Session.send") as send:
                with self.assertRaises(ZBClientException):
                    ZeroBounce(KEY).get_credits()
        send.assert_not_called()

    def test_info_level_sends(self):
        logger = logging.getLogger("urllib3.connectionpool")
        self.addCleanup(logger.setLevel, logger.level)
        logger.setLevel(logging.INFO)
        with _sent_back(b'{"Credits": "5"}', 200, "application/json"):
            self.assertEqual(ZeroBounce(KEY).get_credits().credits, "5")
