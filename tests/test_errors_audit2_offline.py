"""Python audit 2, errors area: IPT / list-evaluator exemption, constructor argument checks, message texts."""

import json
import warnings
from unittest import TestCase
from unittest.mock import patch

from tests.test_transport_guards_offline import KEY, _file_reply
from zerobouncesdk import (
    ZBApiException,
    ZBClientException,
    ZBValidateBatchElement,
    ZeroBounce,
    ZeroBounceWarmup,
)


def _answer(body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return _file_reply(200, raw, "application/json")


def _sent_body():
    seen = {}

    def send(session, request, **kwargs):
        seen["body"] = json.loads(request.body)
        raise ZBApiException("stop")

    return seen, patch("requests.sessions.Session.send", send)


IPT_CALLS = {
    "get_inbox_placement_providers": lambda c: c.get_inbox_placement_providers(),
    "get_inbox_placement_test_types": lambda c: c.get_inbox_placement_test_types(),
    "create_inbox_placement_test": lambda c: c.create_inbox_placement_test("t"),
    "get_inbox_placement_test": lambda c: c.get_inbox_placement_test(1),
    "list_inbox_placement_tests": lambda c: c.list_inbox_placement_tests(),
    "get_inbox_placement_webhook": lambda c: c.get_inbox_placement_webhook(),
    "set_inbox_placement_webhook": lambda c: c.set_inbox_placement_webhook("https://h.example.com/x"),
}


class MessageOnlyExemptionTest(TestCase):
    def test_all_seven_ipt_calls_and_the_list_evaluator_return_a_message_only_body(self):
        client = ZeroBounce(KEY)
        calls = dict(IPT_CALLS)
        calls["get_list_evaluator_result"] = lambda c: c.get_list_evaluator_result("f1")
        for name, call in calls.items():
            for body in ({"Message": "ok"}, {"message": "ok"}, {"detail": "x"}, {}):
                with self.subTest(call=name, body=body), patch("requests.sessions.Session.send", _answer(body)):
                    result = call(client)
                    self.assertEqual(dict(result.__dict__) if hasattr(result, "__dict__") and not isinstance(result, dict) else result, body)

    def test_error_keys_and_success_false_still_raise_on_the_exempt_calls(self):
        client = ZeroBounce(KEY)
        calls = dict(IPT_CALLS)
        calls["get_list_evaluator_result"] = lambda c: c.get_list_evaluator_result("f1")
        for name, call in calls.items():
            for body in ({"error": "bad"}, {"success": False, "message": "no"}):
                with self.subTest(call=name, body=body), patch("requests.sessions.Session.send", _answer(body)):
                    with self.assertRaises(ZBApiException) as caught:
                        call(client)
                    self.assertEqual(caught.exception.status_code, 200)


class ConstructorArgumentTest(TestCase):
    def test_a_non_string_or_missing_key_is_a_client_exception(self):
        for make in (ZeroBounce, ZeroBounceWarmup):
            for value in (None, 5, 5.5, b"key", ["k"], "", "  "):
                with self.subTest(make=make.__name__, value=value), self.assertRaises(ZBClientException):
                    make(value)


class ValidateBatchArgumentTest(TestCase):
    def test_plain_dicts_are_a_client_exception_not_an_attribute_error(self):
        client = ZeroBounce(KEY)
        for batch in ([{"email_address": "a@b.com"}], ["a@b.com"], "a@b.com", 5, [None]):
            with self.subTest(batch=batch), self.assertRaises(ZBClientException):
                client.validate_batch(batch)


class FailureTextTest(TestCase):
    def _text(self, body, call=lambda c: c.file_status("f1")):
        with patch("requests.sessions.Session.send", _answer(body)):
            with self.assertRaises(ZBApiException) as caught:
                call(ZeroBounce(KEY))
        self.assertEqual(caught.exception.status_code, 200)
        return str(caught.exception)

    def test_a_message_that_is_not_text_gets_the_fixed_message(self):
        for body in ({"success": False, "message": {"code": 1}}, {"success": False, "message": [{"a": 1}]},
                     {"success": False, "message": 5}):
            with self.subTest(body=body):
                self.assertEqual(self._text(body), "ZeroBounce returned an error with no message text.")

    def test_the_text_comes_from_whichever_key_holds_it(self):
        for key in ("Message", "detail", "Error", "error_message", "message"):
            with self.subTest(key=key):
                self.assertEqual(self._text({"success": False, key: "Bad thing"}), "Bad thing")
        self.assertEqual(self._text({"success": False}), "Request failed")
        self.assertEqual(self._text({"success": False, "message": "  "}), "Request failed")

    def test_a_list_message_is_joined_with_line_breaks(self):
        self.assertEqual(self._text({"message": ["first", "second"]}), "first\nsecond")
        self.assertEqual(self._text({"success": False, "message": ["first", "second"]}), "first\nsecond")
        self.assertEqual(self._text({"error": ["first", "second"]}), "first\nsecond")

    def test_a_blank_greylist_message_is_an_error_with_status_200(self):
        for blank in ("", "   ", None):
            with self.subTest(blank=blank):
                self.assertEqual(
                    self._text({"Message": blank}, lambda c: c.validate("a@b.com")),
                    "ZeroBounce returned an error with no message text.",
                )

    def test_a_greylist_message_with_text_is_still_a_result(self):
        with patch("requests.sessions.Session.send", _answer({"Message": "greylisted"})):
            ZeroBounce(KEY).validate("a@b.com")


class FileFlagTest(TestCase):
    def test_a_success_that_is_not_boolean_like_is_an_error_naming_the_field(self):
        client = ZeroBounce(KEY)
        for value in ("yes", "no", "maybe", ""):
            for call in (lambda: client.send_evaluated_file("x"), lambda: client.delete_file("x")):
                with self.subTest(value=value), patch(
                    "requests.sessions.Session.send", _answer({"success": value, "file_id": "x"})
                ):
                    with self.assertRaises(ZBApiException) as caught:
                        call()
                    self.assertEqual(caught.exception.status_code, 200)
                    self.assertIn("success", str(caught.exception))

    def test_null_is_accepted_and_true_strings_become_booleans(self):
        client = ZeroBounce(KEY)
        with patch("requests.sessions.Session.send", _answer({"success": None, "file_id": "x"})):
            self.assertIsNone(client.send_evaluated_file("x").success)
        with patch("requests.sessions.Session.send", _answer({"success": "True", "file_id": "x"})):
            self.assertIs(client.send_evaluated_file("x").success, True)


class WarmupBodyTest(TestCase):
    def _body(self, **kwargs):
        seen, patcher = _sent_body()
        with patcher, warnings.catch_warnings(), self.assertRaises(ZBApiException):
            warnings.simplefilter("ignore")
            ZeroBounceWarmup(KEY).add_sending_account("a@example.com", "zb_managed", **kwargs)
        return seen["body"]

    def test_website_goes_out_as_company_website(self):
        body = self._body(email_content={"website": "https://a.example", "company_name": "A"})
        self.assertEqual(body["email_content"], {"company_name": "A", "company_website": "https://a.example"})

    def test_company_website_wins_over_website(self):
        body = self._body(email_content={"website": "https://old.example", "company_website": "https://new.example"})
        self.assertEqual(body["email_content"], {"company_website": "https://new.example"})

    def test_deprecated_keys_are_not_sent_and_warn(self):
        seen, patcher = _sent_body()
        with patcher, warnings.catch_warnings(record=True) as caught, self.assertRaises(ZBApiException):
            warnings.simplefilter("always")
            ZeroBounceWarmup(KEY).add_sending_account(
                "a@example.com", "zb_managed",
                email_content={"industry": "x", "company_name": "A"}, managed_sending={"daily_limit": 5, "weekdays_only": True},
            )
        self.assertEqual(seen["body"]["email_content"], {"company_name": "A"})
        self.assertEqual(seen["body"]["managed_sending"], {"weekdays_only": True})
        self.assertEqual(len(caught), 2)

    def test_unknown_keys_warn_and_are_not_sent(self):
        seen, patcher = _sent_body()
        with patcher, warnings.catch_warnings(record=True) as caught, self.assertRaises(ZBApiException):
            warnings.simplefilter("always")
            ZeroBounceWarmup(KEY).add_sending_account(
                "a@example.com", "zb_managed",
                email_content={"bogus": 1, "company_name": "A"}, managed_sending={"bogus": 2, "weekdays_only": True},
            )
        self.assertEqual(seen["body"]["email_content"], {"company_name": "A"})
        self.assertEqual(seen["body"]["managed_sending"], {"weekdays_only": True})
        self.assertEqual(sum("unknown key (bogus)" in str(w.message) for w in caught), 2)

    def test_wrong_types_are_refused_before_sending(self):
        warmup = ZeroBounceWarmup(KEY)
        bad = [
            {"email_content": {"company_name": 5}},
            {"email_content": {"company_website": 5}}, {"email_content": "x"},
            {"managed_sending": {"timezone": 5}}, {"managed_sending": []},
            {"managed_sending": {"timezone_offset": "3"}},
        ]
        with patch("requests.sessions.Session.send", side_effect=AssertionError("sent")):
            for kwargs in bad:
                with self.subTest(kwargs=kwargs), self.assertRaises(ZBClientException):
                    warmup.add_sending_account("a@example.com", "zb_managed", **kwargs)

    def test_timezone_is_sent_as_a_string(self):
        body = self._body(managed_sending={"timezone": "Asia/Kolkata", "timezone_offset": 5.5})
        self.assertEqual(body["managed_sending"], {"timezone": "Asia/Kolkata", "timezone_offset": 5.5})

    def test_update_sending_account_names_the_invalid_flag(self):
        for value in ("yes", 5, None):
            with self.subTest(value=value), self.assertRaises(ZBClientException) as caught:
                ZeroBounceWarmup(KEY).update_sending_account("a@example.com", 1, 1, value)
            self.assertEqual(str(caught.exception), "Invalid parameter: auto_enable (must be True or False)")


class ResponseTextTest(TestCase):
    def test_repr_and_str_list_every_field(self):
        with patch("requests.sessions.Session.send", _answer({"Credits": "5"})):
            result = ZeroBounce(KEY).get_credits()
        self.assertIn("credits", repr(result).lower())
        self.assertTrue(repr(result).startswith("ZBGetCreditsResponse("))
        with patch("requests.sessions.Session.send", _answer({"address": "a@b.com", "status": "valid"})):
            validated = ZeroBounce(KEY).validate("a@b.com")
        for text in (repr(validated), str(validated)):
            for field in ("address", "status", "sub_status", "domain_age_days", "firstname", "mx_found"):
                self.assertIn(field, text)
        self.assertNotIn(KEY, repr(validated))
