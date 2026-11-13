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


# S4/S7: redaction is closed under encoding (standard.md). The test's own decoder, independent of the SDK's.
FUZZ_SECRET = "k y\"/\\+%&=<>'z"

_FUZZ_ENCODERS = {
    "URL %20": lambda text: __import__("urllib.parse").parse.quote(text, safe=""),
    "URL +": lambda text: __import__("urllib.parse").parse.quote_plus(text),
    "JSON": lambda text: json.dumps(text)[1:-1],
    "JSON \\/": lambda text: json.dumps(text)[1:-1].replace("/", "\\/"),
}


def _test_json_unescape(text):
    import re

    simple = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    return re.sub(
        r'\\(u[0-9a-fA-F]{4}|["\\/bfnrt])',
        lambda m: chr(int(m.group(1)[1:], 16)) if m.group(1)[0] == "u" else simple[m.group(1)],
        text,
    )


def _views(text, layers=3):
    from urllib.parse import unquote, unquote_plus

    decoders = (unquote, unquote_plus, lambda t: t.replace("+", " "), _test_json_unescape)
    views = {text}
    frontier = {text}
    for _ in range(layers):
        frontier = {decode(view) for view in frontier for decode in decoders} - views
        views |= frontier
    return views


def _error_texts(error, seen=None):
    """The message, repr, args, every attribute and the whole cause/context chain of ``error``."""
    seen = seen if seen is not None else set()
    if error is None or id(error) in seen:
        return []
    seen.add(id(error))
    texts = [str(error), repr(error), repr(error.args), repr(vars(error))]
    texts += _error_texts(error.__cause__, seen) + _error_texts(error.__context__, seen)
    return texts


def _fuzz_forms(secret, seed=8259, count=120):
    """Every sequence of up to three encodings of ``secret``, plus random ones wrapped in random text."""
    import random

    names = list(_FUZZ_ENCODERS)
    sequences = [list(seq) for depth in (1, 2, 3) for seq in product(names, repeat=depth)]
    rng = random.Random(seed)
    sequences += [[rng.choice(names) for _ in range(rng.randint(1, 3))] for _ in range(count)]
    for sequence in sequences:
        form = secret
        for name in sequence:
            form = _FUZZ_ENCODERS[name](form)
        yield " > ".join(sequence), form


class EncodingClosureFuzzTest(TestCase):
    """S4/S7: a secret under any composition of up to three encodings never survives in any decoded view of an
    error: message, args, attributes or cause chain."""

    BODIES = (
        lambda form: (400, f"rejected: {form}".encode(), "text/plain"),
        lambda form: (200, f'{{"error": "Invalid API key {form}"}}'.encode(), "application/json"),
        lambda form: (200, f'{{"success": false, "message": "rejected {form}"}}'.encode(), "application/json"),
        lambda form: (400, f'{{"message": "bad request {form}"}}'.encode(), "application/json"),
        lambda form: (200, f"<html><title>denied {form}</title></html>".encode(), "text/html"),
    )

    def _leaks(self, secret, calls):
        import random

        from tests.test_transport_guards_offline import _quiet

        rng = random.Random(7)
        leaks = []
        for label, form in _fuzz_forms(secret):
            status, body, content_type = rng.choice(self.BODIES)(form)
            with patch(
                "requests.sessions.Session.send",
                lambda session, request, **kw: offline._response(status, body, content_type),
            ):
                for name, call in calls:
                    try:
                        _quiet(call)
                    except Exception as error:  # noqa: BLE001 - every error is inspected
                        if any(secret in view for text in _error_texts(error) for view in _views(text)):
                            leaks.append((name, label, status))
        return leaks

    def test_the_api_key_never_survives_any_encoding(self):
        from tests.test_transport_guards_offline import client_calls

        client = ZeroBounce(FUZZ_SECRET)
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        calls = [(name, call) for name, variants in client_calls(client, out).items() for call in variants[:1]]
        self.assertEqual(self._leaks(FUZZ_SECRET, calls), [])

    def test_the_warmup_key_never_survives_any_encoding(self):
        from tests.test_transport_guards_offline import warmup_calls

        warmup = ZeroBounceWarmup(FUZZ_SECRET)
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        calls = [(name, lambda c=call: c(warmup)) for name, call in warmup_calls(out).items()]
        self.assertEqual(self._leaks(FUZZ_SECRET, calls), [])

    def test_smtp_credentials_never_survive_any_encoding(self):
        warmup = ZeroBounceWarmup(KEY)
        username = "smtp" + FUZZ_SECRET
        calls = [
            ("password", lambda: warmup.test_smtp_configuration("s@example.com", "user", FUZZ_SECRET, "smtp.example.com", 587)),
        ]
        self.assertEqual(self._leaks(FUZZ_SECRET, calls), [])
        calls = [
            ("username", lambda: warmup.test_smtp_configuration("s@example.com", username, "pw", "smtp.example.com", 587)),
        ]
        self.assertEqual(self._leaks(username, calls), [])

    def test_text_without_a_secret_is_kept(self):
        self.assertEqual(_redact_secrets("Invalid email a+b%20c\\/d", [FUZZ_SECRET]), "Invalid email a+b%20c\\/d")


class DecodeDepthTest(TestCase):
    """S4: the decode check covers four layers, the SDK's own request encoding plus three echo layers
    (standard.md): a proxy that URL-encodes the request URL three times over still hands back no key."""

    SECRET = 'probe"key/ZQXMARK01+23&ab c\\xyz'

    @staticmethod
    def _three_times(text):
        from urllib.parse import quote

        return quote(quote(quote(text, safe=""), safe=""), safe="")

    def test_a_key_under_four_layers_is_omitted(self):
        from urllib.parse import quote_plus

        from zerobouncesdk.zerobouncesdk import CREDENTIAL_OMITTED_MESSAGE

        body = self._three_times(f"GET /v2/getcredits?api_key={quote_plus(self.SECRET)} HTTP/1.1")
        self.assertEqual(_redact_secrets(body, [self.SECRET]), CREDENTIAL_OMITTED_MESSAGE)
        self.assertTrue(any(self.SECRET in view for view in _views(body, layers=4)))

    def test_every_call_omits_a_url_echoed_under_three_more_encodings(self):
        from tests.test_transport_guards_offline import _BASE_URL_ATTRIBUTES, LocalServer, _quiet, client_calls

        server = LocalServer(lambda h: (400, {"Content-Type": "text/plain"}, self._three_times(h.path).encode()))
        self.addCleanup(server.close)
        patcher = patch("zerobouncesdk.zerobouncesdk._https_url", lambda url: url)
        patcher.start()
        self.addCleanup(patcher.stop)
        client = ZeroBounce(self.SECRET)
        client._base_url = server.url + "/v2"
        for attribute, path in _BASE_URL_ATTRIBUTES.items():
            setattr(client, attribute, server.url + path)
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        leaks, errors = [], 0
        for name, variants in client_calls(client, out).items():
            for call in variants:
                try:
                    _quiet(call)
                except Exception as error:  # noqa: BLE001 - every error is inspected
                    errors += 1
                    if any(self.SECRET in view for text in _error_texts(error) for view in _views(text, layers=4)):
                        leaks.append(name)
        self.assertGreater(errors, 40)
        self.assertEqual(leaks, [])


class SurrogatePairDecodeTest(TestCase):
    """S4/S7: ``\\uXXXX\\uXXXX`` surrogate pairs are joined when decoding, so a non-BMP secret whose every
    character the echo ``\\u``-escaped (on top of the SDK's own ASCII JSON escaping) is still found."""

    def test_a_u_escaped_surrogate_pair_is_decoded(self):
        from zerobouncesdk.zerobouncesdk import CREDENTIAL_OMITTED_MESSAGE

        secret = "pw\U0001F600ZQXMARK"
        once = json.dumps(secret)[1:-1]  # pw😀ZQXMARK, what requests sends for a JSON body
        body = "".join("\\u%04x" % ord(char) for char in once)
        self.assertEqual(_redact_secrets(body, [secret]), CREDENTIAL_OMITTED_MESSAGE)

    def test_a_smtp_password_echoed_that_way_does_not_leak(self):
        secret = "pw\U0001F600ZQXMARK"
        body = "".join("\\u%04x" % ord(char) for char in json.dumps(secret)[1:-1])
        reply = json.dumps({"error": "rejected " + body}).encode()
        warmup = ZeroBounceWarmup(KEY)
        with patch(
            "requests.sessions.Session.send",
            lambda session, request, **kw: offline._response(400, reply, "application/json"),
        ):
            with self.assertRaises(ZBApiException) as caught:
                warmup.test_smtp_configuration("s@example.com", "user", secret, "smtp.example.com", 587)
        self.assertNotIn("ZQXMARK", str(caught.exception))


class DecodeStepsTest(TestCase):
    """S4: every decode step of the check is needed: lower-case ``%xx`` (next to invalid UTF-8), ``+`` as space,
    JSON escapes and ``\\uXXXX``; a NUL or ``%00`` before the secret does not end the check."""

    SECRET = "zq x/ZQXMARK"

    @staticmethod
    def _lower_hex(text):
        return "".join("%%%02x" % byte for byte in text.encode())

    def test_each_encoding_alone_is_caught(self):
        from zerobouncesdk.zerobouncesdk import CREDENTIAL_OMITTED_MESSAGE

        secret = self.SECRET
        u_escaped = "".join("\\u%04x" % ord(char) for char in secret)
        bodies = {
            "lower-case %xx after invalid UTF-8": "%ff%fe" + self._lower_hex(secret),
            "+ as space, then %xx": self._lower_hex(secret.split(" ")[0]) + "+" + self._lower_hex(secret.split(" ")[1]),
            "JSON \\u escapes": u_escaped,
            "\\u escapes, URL-encoded": self._lower_hex(u_escaped),
            "a literal + kept, %xx decoded": "zq+x" + self._lower_hex("/ZQXMARK"),
            "NUL first": "\x00" + u_escaped,
            "%00 first": "%00" + self._lower_hex(secret),
        }
        for label, body in bodies.items():
            secrets = ["zq+x/ZQXMARK"] if label.startswith("a literal +") else [secret]
            self.assertEqual(_redact_secrets("rejected " + body, secrets), CREDENTIAL_OMITTED_MESSAGE, label)

    def test_every_utf8_sequence_length_is_decoded(self):
        """%-decoding reads UTF-8: a 2-, 3- and 4-byte character spelled as lower-case %xx (a spelling no mask
        form covers) is still found."""
        from zerobouncesdk.zerobouncesdk import CREDENTIAL_OMITTED_MESSAGE

        for length, char in ((2, "\u00e9"), (3, "\u20ac"), (4, "\U0001F600")):
            self.assertEqual(len(char.encode()), length)
            secret = "zq" + char + "ZQXMARK"
            for body in (self._lower_hex(secret), "zq" + self._lower_hex(char) + "ZQXMARK"):
                self.assertEqual(_redact_secrets("rejected " + body, [secret]), CREDENTIAL_OMITTED_MESSAGE, length)
            # The same through + as space (unquote_plus).
            spaced = "zq " + char + "ZQXMARK"
            body = "zq+" + self._lower_hex(char) + "ZQXMARK"
            self.assertEqual(_redact_secrets("rejected " + body, [spaced]), CREDENTIAL_OMITTED_MESSAGE, length)

    def test_plus_as_space_alone_is_a_decode_step(self):
        """A secret holding a literal %xx, echoed with only its space turned into +, is found only by reading +
        as a space without %-decoding."""
        from zerobouncesdk.zerobouncesdk import CREDENTIAL_OMITTED_MESSAGE

        secret = "zq x%41ZQXMARK"
        self.assertEqual(_redact_secrets("rejected zq+x%41ZQXMARK", [secret]), CREDENTIAL_OMITTED_MESSAGE)
