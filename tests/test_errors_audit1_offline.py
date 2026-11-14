"""Python audit 1, errors area: message-only bodies, strict success flags, argument checks, timeouts."""

import inspect
import io
import json
import tempfile
import warnings
from datetime import date, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from tests.test_transport_guards_offline import KEY, _file_reply, _quiet, client_calls
from zerobouncesdk import ZBApiException, ZBClientException, ZeroBounce, ZeroBounceWarmup

MESSAGE_ONLY = [
    {"Message": "nope"}, {"message": "nope"}, {"error": "nope"}, {"error_message": "nope"},
    {"Error": "nope"}, {"detail": "nope"}, {"message": ["a", "b"]}, {"message": ""}, {},
]
# Raw-JSON calls, and the calls whose documented success is a bare message or empty.
NOT_TYPED = {
    "add_filter", "delete_filter", "list_filters", "delete_inbox_placement_test", "set_inbox_placement_webhook",
    "get_file", "scoring_get_file", "email_finder_get_file", "domain_search_get_file",
}


def _answer(body):
    return _file_reply(200, json.dumps(body).encode(), "application/json")


class MessageOnlyBodiesTest(TestCase):
    def test_every_typed_call_raises_on_every_message_only_body(self):
        out = str(Path(tempfile.mkdtemp()) / "out.csv")
        calls = client_calls(ZeroBounce(KEY), out)
        wrong = []
        for body in MESSAGE_ONLY:
            with patch("requests.sessions.Session.send", _answer(body)):
                for name, variants in calls.items():
                    if name in NOT_TYPED:
                        continue
                    for call in variants:
                        if name == "validate" and body == {"Message": "nope"}:
                            continue
                        try:
                            _quiet(call)
                        except ZBApiException as error:
                            if error.status_code != 200:
                                wrong.append((name, body, error.status_code))
                        except Exception as error:  # noqa: BLE001
                            wrong.append((name, body, type(error).__name__))
                        else:
                            wrong.append((name, body, "result"))
        self.assertEqual(wrong, [])

    def test_validate_greylist_message_stays_a_result_but_lowercase_is_an_error(self):
        client = ZeroBounce(KEY)
        with patch("requests.sessions.Session.send", _answer({"Message": "greylisted, try later"})):
            self.assertEqual(client.validate("a@b.com").message if hasattr(client.validate("a@b.com"), "message") else "", "greylisted, try later")
        with patch("requests.sessions.Session.send", _answer({"message": "greylisted"})):
            with self.assertRaises(ZBApiException):
                client.validate("a@b.com")

    def test_raw_json_filter_calls_keep_their_message_answer(self):
        with patch("requests.sessions.Session.send", _answer({"Message": "Filter has been added."})):
            self.assertEqual(ZeroBounce(KEY).add_filter("allow", "email", "a@b.com"), {"Message": "Filter has been added."})


class StrictSuccessFlagTest(TestCase):
    def test_every_false_spelling_of_success_is_an_error(self):
        client = ZeroBounce(KEY)
        for value in ("0", "False ", " false", "FALSE", 0, False):
            with patch("requests.sessions.Session.send", _answer({"success": value, "message": "Failed"})):
                for call in (lambda: client.file_status("f1"), lambda: client.delete_file("f1")):
                    with self.subTest(value=value), self.assertRaises(ZBApiException) as caught:
                        call()
                    self.assertEqual(caught.exception.status_code, 200)

    def test_raw_calls_treat_them_as_errors_too(self):
        with patch("requests.sessions.Session.send", _answer({"success": "0", "message": "no"})):
            with self.assertRaises(ZBApiException):
                ZeroBounce(KEY).add_filter("allow", "email", "a@b.com")

    def test_true_spellings_are_results(self):
        with patch("requests.sessions.Session.send", _answer({"success": "1", "message": "ok", "file_id": "f"})):
            ZeroBounce(KEY).delete_file("f1")


class ErrorObjectTest(TestCase):
    def test_an_error_object_has_no_python_repr_in_the_message(self):
        with patch("requests.sessions.Session.send", _answer({"error": {"code": 1}})):
            with self.assertRaises(ZBApiException) as caught:
                ZeroBounce(KEY).get_credits()
        self.assertEqual(str(caught.exception), "ZeroBounce returned an error with no message text.")


def _never_sent():
    return patch("requests.sessions.Session.send", side_effect=AssertionError("a request was sent"))


class BlankOptionalFieldsTest(TestCase):
    def _sent(self, call):
        seen = {}

        def send(session, request, **kwargs):
            seen["url"] = request.url
            seen["body"] = request.body
            raise ZBApiException("stop")

        with patch("requests.sessions.Session.send", send):
            with self.assertRaises(ZBApiException):
                call()
        return seen

    def test_validate_omits_a_blank_ip_address(self):
        for blank in ("", "   ", None):
            self.assertNotIn("ip_address", self._sent(lambda: ZeroBounce(KEY).validate("a@b.com", ip_address=blank))["url"])
        self.assertIn("ip_address=1.2.3.4", self._sent(lambda: ZeroBounce(KEY).validate("a@b.com", ip_address="1.2.3.4"))["url"])

    def test_send_file_omits_a_blank_return_url(self):
        path = Path(tempfile.mkdtemp()) / "in.csv"
        path.write_text("a@b.com\n")
        for blank in ("", "  "):
            body = self._sent(lambda: ZeroBounce(KEY).send_file(str(path), 1, return_url=blank))["body"]
            self.assertNotIn(b"return_url", body)
        body = self._sent(lambda: ZeroBounce(KEY).send_file(str(path), 1, return_url="https://x.example/cb"))["body"]
        self.assertIn(b"return_url", body)


VALID = {
    "email": "a@b.com", "file_id": "f1", "file_name": "x.csv", "file_path": "x.csv", "name": "t1",
    "webhook_url": "https://x.example/h", "domain": "example.com", "download_path": "out.csv",
    "email_address_column": 1, "domain_column": 1, "has_header_row": False, "return_url": "https://x.example/cb",
    "rule": "allow", "target": "email", "value": "a@b.com", "start_date": date(2026, 1, 1),
    "end_date": date(2026, 1, 2), "file_stream": io.BytesIO(b"a@b.com"), "first_name_column": 1,
    "email_batch": None,
}
TEXT_PARAMS = ("email", "file_id", "file_name", "file_path", "name", "webhook_url", "domain", "rule", "target", "value")
SKIP_CALLS = {"guess_format", "find_email_format", "find_domain"}  # domain/company_name pairs: tested below


class ArgumentSweepTest(TestCase):
    def test_bad_text_arguments_raise_before_anything_is_sent(self):
        client = ZeroBounce(KEY)
        failures = []
        for name, method in inspect.getmembers(client, inspect.ismethod):
            if name.startswith("_") or name in SKIP_CALLS:
                continue
            params = inspect.signature(method).parameters
            for param in params:
                if param not in TEXT_PARAMS:
                    continue
                optional = params[param].default is not inspect.Parameter.empty
                for bad in (None, "", "  ", 5):
                    if optional and bad is None:
                        continue
                    kwargs = {}
                    for other, spec in params.items():
                        if spec.default is not inspect.Parameter.empty:
                            continue
                        kwargs[other] = VALID.get(other, "x")
                        if other == "file_stream":
                            kwargs[other] = io.BytesIO(b"x")
                    kwargs[param] = bad
                    if param == "file_path" and "file_name" in params:
                        continue
                    with _never_sent():
                        try:
                            _quiet(lambda: method(**kwargs))
                        except ZBClientException:
                            pass
                        except Exception as error:  # noqa: BLE001
                            failures.append((name, param, bad, type(error).__name__))
                        else:
                            failures.append((name, param, bad, "no error"))
        self.assertEqual(failures, [])

    def test_blank_domain_and_names_for_the_finders(self):
        client = ZeroBounce(KEY)
        with _never_sent():
            for call in (
                lambda: client.find_email_format(domain="  "),
                lambda: client.find_email_format(domain=None, company_name=None),
                lambda: client.find_domain(domain="  "),
                lambda: client.find_domain(domain=5),
                lambda: client.guess_format(None),
                lambda: client.guess_format("  "),
            ):
                with self.assertRaises(ZBClientException):
                    _quiet(call)

    def test_api_usage_arguments(self):
        client = ZeroBounce(KEY)
        with _never_sent():
            for start, end in ((None, date(2026, 1, 1)), (date(2026, 1, 1), None), ("2026-01-01", date(2026, 1, 2)),
                               (date(2026, 2, 1), date(2026, 1, 1))):
                with self.assertRaises(ZBClientException):
                    client.get_api_usage(start, end)

    def test_filter_values_with_only_whitespace_are_refused(self):
        with _never_sent():
            for call in (lambda: ZeroBounce(KEY).add_filter("allow", "email", "  "),
                         lambda: ZeroBounce(KEY).delete_filter("allow", "email", None)):
                with self.assertRaises(ZBClientException):
                    call()

    def test_columns_must_be_integers(self):
        with _never_sent():
            with self.assertRaises(ZBClientException):
                ZeroBounce(KEY).send_domain_search_file("x.csv", "1")
            with self.assertRaises(ZBClientException):
                ZeroBounce(KEY).send_file("x.csv", None)


class TimeoutValidationTest(TestCase):
    def test_the_constructor_refuses_a_non_positive_or_wrong_type_timeout(self):
        for cls in (ZeroBounce, ZeroBounceWarmup):
            for bad in (timedelta(0), timedelta(seconds=-1), 10, "10", 1.5):
                with self.subTest(cls=cls.__name__, bad=bad), self.assertRaises(ZBClientException):
                    cls(KEY, timeout=bad)
            cls(KEY, timeout=timedelta(seconds=5))

    def test_validate_timeout_is_whole_seconds_in_range(self):
        client = ZeroBounce(KEY)
        with _never_sent():
            for bad in (3.5, "10", True, 2, 61, -1):
                with self.subTest(bad=bad), self.assertRaises(ZBClientException):
                    client.validate("a@b.com", timeout=bad)
            for bad in (10.5, "20", 9, 121):
                with self.subTest(bad=bad), self.assertRaises(ZBClientException):
                    client.validate_batch([__import__("zerobouncesdk").ZBValidateBatchElement("a@b.com")], timeout=bad)
