"""Behaviour every ZeroBounce SDK shares for the same API response (sdk-docs standard, section 3)."""

import io
import json
import os
import tempfile
from datetime import date
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests

from zerobouncesdk import (
    ZBApiException,
    ZBClientException,
    ZBGetFileOptions,
    ZBValidateBatchElement,
    ZeroBounce,
)

KEY = "parity-key"


class FakeServer:
    """Answers every request with one canned response and records what was sent."""

    def __init__(self, body="{}", status=200, content_type="application/json"):
        self.body, self.status, self.content_type = body, status, content_type
        self.requests = []

    def __call__(self, request, **kwargs):
        self.requests.append(request)
        response = requests.Response()
        response.status_code = self.status
        response._content = self.body.encode() if isinstance(self.body, str) else self.body
        response.headers["Content-Type"] = self.content_type
        response.url = request.url
        response.request = request
        return response

    def sent(self):
        """Query and form fields (or JSON body) of the last request, as a flat dict."""
        request = self.requests[-1]
        fields = {k: v[0] for k, v in parse_qs(urlsplit(request.url).query).items()}
        body = request.body or b""
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        if body.startswith("{"):
            fields.update(json.loads(body))
        elif "=" in body and "Content-Disposition" not in body:
            fields.update({k: v[0] for k, v in parse_qs(body).items()})
        return fields


class ParityTestCase(TestCase):
    def serve(self, body="{}", status=200, content_type="application/json"):
        server = FakeServer(body, status, content_type)
        patcher = patch("requests.sessions.Session.send", lambda session, request, **kw: server(request, **kw))
        patcher.start()
        self.addCleanup(patcher.stop)
        return server

    def setUp(self):
        self.client = ZeroBounce(KEY)


class GreylistTest(ParityTestCase):
    def test_the_greylist_message_is_a_result(self):
        self.serve('{"Message":"Greylist validation still in progress..."}')
        for use_post in (False, True):
            result = self.client.validate("a@example.com", greylist_processing=True, use_post=use_post)
            self.assertEqual(result.message, "Greylist validation still in progress...")


class TwoHundredErrorTest(ParityTestCase):
    def test_error_message_without_success_is_an_error_with_status_200(self):
        self.serve('{"error_message":"Invalid API key"}')
        for call in (
            self.client.get_credits,
            lambda: self.client.validate("a@example.com"),
            lambda: self.client.file_status("f1"),
            lambda: self.client.get_inbox_placement_providers(),
        ):
            with self.assertRaises(ZBApiException) as caught:
                call()
            self.assertEqual(str(caught.exception), "Invalid API key")
            self.assertEqual(caught.exception.status_code, 200)

    def test_dead_key_and_success_false_carry_status_200(self):
        for body in ('{"error":"Invalid API key"}', '{"success":false,"message":"File cannot be found."}'):
            self.serve(body)
            with self.assertRaises(ZBApiException) as caught:
                self.client.file_status("f1")
            self.assertEqual(caught.exception.status_code, 200, body)

    def test_error_message_with_success_is_a_result(self):
        self.serve('{"success":true,"file_status":"Complete","error_message":"none"}')
        self.assertEqual(self.client.file_status("f1").file_status, "Complete")

    def test_message_only_bodies_are_errors_for_the_finder_and_domain_search(self):
        for body, text in (
            ('{"Message":"Invalid API key or your account ran out of credits"}',
             "Invalid API key or your account ran out of credits"),
            ('{"detail":"Not allowed"}', "Not allowed"),
            ('{"error_message":"Not allowed"}', "Not allowed"),
        ):
            self.serve(body)
            for call in (
                lambda: self.client.find_domain(domain="example.com"),
                lambda: self.client.find_email_format(first_name="Ann", domain="example.com"),
                lambda: self.client.find_domain(domain="example.com", use_post=True),
            ):
                with self.assertRaises(ZBApiException) as caught:
                    call()
                self.assertEqual(str(caught.exception), text, body)
                self.assertEqual(caught.exception.status_code, 200, body)

    def test_a_batch_account_error_carries_status_200(self):
        self.serve('{"email_batch":[],"errors":[{"email_address":"all",'
                   '"error":"Invalid API Key or your account ran out of credits"}]}')
        with self.assertRaises(ZBApiException) as caught:
            self.client.validate_batch([ZBValidateBatchElement("a@example.com")])
        self.assertEqual(str(caught.exception), "Invalid API Key or your account ran out of credits")
        self.assertEqual(caught.exception.status_code, 200)


class ResponseFlagTest(ParityTestCase):
    def test_validate_flags_are_booleans_or_none(self):
        self.serve('{"address":"a@example.com","status":"valid","mx_found":"unknown",'
                   '"free_email":"FALSE","catchall_domain":"1"}')
        result = self.client.validate("a@example.com")
        self.assertIsNone(result.mx_found)
        self.assertIs(result.free_email, False)
        self.assertIs(result.catchall_domain, True)

    def test_parse_bool_accepts_only_booleans(self):
        from zerobouncesdk._zb_utils import parse_bool

        for value, expected in (
            (True, True), (False, False), (1, True), (0, False),
            ("true", True), (" FALSE ", False), ("1", True), ("0", False),
            ("unknown", None), ("", None), (None, None), (2, None), ("yes", None),
        ):
            self.assertIs(parse_bool(value), expected, repr(value))

    def test_activity_found_is_a_boolean(self):
        for body, expected in (
            ('{"found":"false","active_in_days":null}', False),
            ('{"found":"true","active_in_days":"30"}', True),
            ('{"found":false}', False),
            ('{"found":true}', True),
            ('{"found":"unknown"}', None),
        ):
            self.serve(body)
            self.assertIs(self.client.get_activity("a@example.com").found, expected, body)


class RawStatusTest(ParityTestCase):
    def test_unknown_status_values_stay_available(self):
        self.serve('{"address":"a@example.com","status":"brand_new","sub_status":"newer_still"}')
        with self.assertWarns(UserWarning):
            result = self.client.validate("a@example.com")
        self.assertIsNone(result.status)
        self.assertEqual(result.raw_status, "brand_new")
        self.assertEqual(result.raw_sub_status, "newer_still")


class StrictBooleanTest(ParityTestCase):
    def setUp(self):
        super().setUp()
        self.server = self.serve('{"success":true,"address":"a@example.com","status":"valid","email_batch":[]}')

    def test_string_false_is_sent_as_false(self):
        self.client.validate("a@example.com", activity_data="false", verify_plus="TRUE", domain_info=0)
        self.assertEqual(self.server.sent()["activity_data"], "false")
        self.assertEqual(self.server.sent()["verify_plus"], "true")
        self.assertEqual(self.server.sent()["domain_info"], "false")
        self.client.validate_batch([ZBValidateBatchElement("a@example.com")], activity_data="false")
        self.assertIs(self.server.sent()["activity_data"], False)
        self.client.validate_s3file("f.csv", "false", remove_duplicates="0", return_url="https://example.com/d")
        self.assertEqual(self.server.sent()["has_header_row"], "false")
        self.assertEqual(self.server.sent()["remove_duplicates"], "false")

    def test_anything_else_is_rejected_before_sending(self):
        calls = [
            lambda: self.client.validate("a@example.com", activity_data="yes"),
            lambda: self.client.validate("a@example.com", greylist_processing=2),
            lambda: self.client.validate_batch([ZBValidateBatchElement("a@example.com")], verify_plus="no"),
            lambda: self.client.send_file_stream(io.BytesIO(b"e\n"), "f.csv", 1, has_header_row="yes"),
            lambda: self.client.send_file_stream(io.BytesIO(b"e\n"), "f.csv", 1, allow_phase_2="maybe"),
            lambda: self.client.send_domain_search_file_stream(io.BytesIO(b"d\n"), "f.csv", 1, has_header_row="y"),
            lambda: self.client.get_file("f1", os.path.join(tempfile.mkdtemp(), "o.csv"),
                                         ZBGetFileOptions(activity_data="nope")),
        ]
        for method in ("validate_s3file", "score_s3file", "email_finder_s3file", "domain_search_s3file",
                       "validate_sftpfile", "score_sftpfile", "email_finder_sftpfile", "domain_search_sftpfile"):
            calls.append(lambda m=method: getattr(self.client, m)("f.csv", "yes", return_url="https://e.example/d"))
            calls.append(lambda m=method: getattr(self.client, m)("f.csv", True, remove_duplicates="nope",
                                                                  return_url="https://e.example/d"))
        for call in calls:
            with self.assertRaisesRegex(ZBClientException, "must be true or false"):
                call()
        self.assertEqual(self.server.requests, [])


class PerApiBaseUrlTest(ParityTestCase):
    def test_trailing_slashes_on_per_api_base_urls_are_dropped(self):
        server = self.serve('{"success":true,"file_status":"Complete","file_id":"f1"}')
        names = ("BULK_BASE_URL", "BULK_ROOT_URL", "EMAIL_FINDER_BASE_URL", "DOMAIN_SEARCH_BASE_URL",
                 "SCORING_BASE_URL", "LIST_EVALUATOR_BASE_URL", "INBOX_PLACEMENT_BASE_URL")
        for name in names:
            setattr(self.client, name, getattr(ZeroBounce, name) + "//")
        self.client.file_status("f1")
        self.client.scoring_file_status("f1")
        self.client.email_finder_file_status("f1")
        self.client.domain_search_file_status("f1")
        self.client.send_evaluated_file("f1")
        self.client.get_list_evaluator_result("f1")
        self.client.export_s3file("f1")
        self.client.get_inbox_placement_webhook()
        for request in server.requests:
            self.assertNotIn("//", urlsplit(request.url).path, request.url)


class HttpsSweepTest(ParityTestCase):
    """Every public request method refuses to send the key anywhere but https."""

    NOT_REQUESTS = {"get_file_json_indicates_error"}

    def calls(self, client, out):
        stream = lambda: io.BytesIO(b"email\na@example.com\n")  # noqa: E731
        d = "https://example.com/d"
        return {
            "get_credits": [lambda: client.get_credits(), lambda: client.get_credits(use_post=True)],
            "get_api_usage": [lambda: client.get_api_usage(date(2024, 1, 1), date(2024, 1, 2)),
                              lambda: client.get_api_usage(date(2024, 1, 1), date(2024, 1, 2), use_post=True)],
            "get_activity": [lambda: client.get_activity("a@example.com"),
                             lambda: client.get_activity("a@example.com", use_post=True)],
            "score_email": [lambda: client.score_email("a@example.com"),
                            lambda: client.score_email("a@example.com", use_post=True)],
            "validate": [lambda: client.validate("a@example.com"),
                         lambda: client.validate("a@example.com", use_post=True)],
            "validate_batch": [lambda: client.validate_batch([ZBValidateBatchElement("a@example.com")])],
            "send_file": [lambda: client.send_file(__file__, 1)],
            "send_file_stream": [lambda: client.send_file_stream(stream(), "f.csv", 1)],
            "scoring_send_file": [lambda: client.scoring_send_file(__file__, 1)],
            "scoring_send_file_stream": [lambda: client.scoring_send_file_stream(stream(), "f.csv", 1)],
            "file_status": [lambda: client.file_status("f1")],
            "scoring_file_status": [lambda: client.scoring_file_status("f1")],
            "get_file": [lambda: client.get_file("f1", out), lambda: client.get_file("f1", out, stream=True)],
            "scoring_get_file": [lambda: client.scoring_get_file("f1", out)],
            "delete_file": [lambda: client.delete_file("f1")],
            "scoring_delete_file": [lambda: client.scoring_delete_file("f1")],
            "send_email_finder_file": [lambda: client.send_email_finder_file(__file__, 1, first_name_column=2)],
            "send_email_finder_file_stream": [
                lambda: client.send_email_finder_file_stream(stream(), "f.csv", 1, first_name_column=2)],
            "email_finder_file_status": [lambda: client.email_finder_file_status("f1")],
            "email_finder_get_file": [lambda: client.email_finder_get_file("f1", out)],
            "email_finder_delete_file": [lambda: client.email_finder_delete_file("f1")],
            "send_domain_search_file": [lambda: client.send_domain_search_file(__file__, 1)],
            "send_domain_search_file_stream": [lambda: client.send_domain_search_file_stream(stream(), "f.csv", 1)],
            "domain_search_file_status": [lambda: client.domain_search_file_status("f1")],
            "domain_search_get_file": [lambda: client.domain_search_get_file("f1", out)],
            "domain_search_delete_file": [lambda: client.domain_search_delete_file("f1")],
            "send_list_evaluator_file": [lambda: client.send_list_evaluator_file(__file__, 1)],
            "send_list_evaluator_file_stream": [lambda: client.send_list_evaluator_file_stream(stream(), "f.csv", 1)],
            "get_list_evaluator_result": [lambda: client.get_list_evaluator_result("f1")],
            "send_evaluated_file": [lambda: client.send_evaluated_file("f1")],
            "add_filter": [lambda: client.add_filter("allow", "email", "a@example.com")],
            "list_filters": [lambda: client.list_filters(), lambda: client.list_filters(use_post=True)],
            "delete_filter": [lambda: client.delete_filter("allow", "email", "a@example.com")],
            "list_s3files": [lambda: client.list_s3files()],
            "validate_s3file": [lambda: client.validate_s3file("f.csv", True, return_url=d)],
            "score_s3file": [lambda: client.score_s3file("f.csv", True, return_url=d)],
            "export_s3file": [lambda: client.export_s3file("f1")],
            "email_finder_s3file": [lambda: client.email_finder_s3file("f.csv", True, return_url=d)],
            "domain_search_s3file": [lambda: client.domain_search_s3file("f.csv", True, return_url=d)],
            "validate_sftpfile": [lambda: client.validate_sftpfile("f.csv", True, return_url=d)],
            "score_sftpfile": [lambda: client.score_sftpfile("f.csv", True, return_url=d)],
            "email_finder_sftpfile": [lambda: client.email_finder_sftpfile("f.csv", True, return_url=d)],
            "domain_search_sftpfile": [lambda: client.domain_search_sftpfile("f.csv", True, return_url=d)],
            "export_sftpfile": [lambda: client.export_sftpfile("f1")],
            "get_inbox_placement_providers": [lambda: client.get_inbox_placement_providers()],
            "get_inbox_placement_test_types": [lambda: client.get_inbox_placement_test_types()],
            "create_inbox_placement_test": [lambda: client.create_inbox_placement_test("Spring launch")],
            "get_inbox_placement_test": [lambda: client.get_inbox_placement_test(1)],
            "list_inbox_placement_tests": [lambda: client.list_inbox_placement_tests()],
            "delete_inbox_placement_test": [lambda: client.delete_inbox_placement_test(1)],
            "get_inbox_placement_webhook": [lambda: client.get_inbox_placement_webhook()],
            "set_inbox_placement_webhook": [lambda: client.set_inbox_placement_webhook("https://example.com/h")],
            "guess_format": [lambda: client.guess_format("example.com")],
            "find_email_format": [lambda: client.find_email_format(domain="example.com"),
                                  lambda: client.find_email_format(domain="example.com", use_post=True)],
            "find_domain": [lambda: client.find_domain(domain="example.com"),
                            lambda: client.find_domain(domain="example.com", use_post=True)],
        }

    def test_every_public_request_method_refuses_http(self):
        server = self.serve('{"success":true}')
        client = ZeroBounce(KEY)
        client._base_url = "http://api.example.test/v2"
        for name in ("BULK_BASE_URL", "BULK_ROOT_URL", "EMAIL_FINDER_BASE_URL", "DOMAIN_SEARCH_BASE_URL",
                     "SCORING_BASE_URL", "LIST_EVALUATOR_BASE_URL", "INBOX_PLACEMENT_BASE_URL"):
            setattr(client, name, "http" + getattr(ZeroBounce, name)[len("https"):])
        calls = self.calls(client, os.path.join(tempfile.mkdtemp(), "out.csv"))
        public = {
            name for name in dir(ZeroBounce)
            if not name.startswith("_") and callable(getattr(ZeroBounce, name))
        } - self.NOT_REQUESTS
        self.assertEqual(public - set(calls), set(), "public methods missing from the sweep")
        for name, variants in calls.items():
            for call in variants:
                with self.assertRaisesRegex(ZBClientException, "https://", msg=name):
                    with self.assertWarns(DeprecationWarning) if name == "guess_format" else _nothing():
                        call()
        self.assertEqual(server.requests, [])


class _nothing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
