"""Offline edge cases: transport failures, error bodies, and every optional field on the wire."""

import json
import tempfile
from io import BytesIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from requests.exceptions import ConnectionError as RequestsConnectionError

from tests import test_offline_api as offline
from zerobouncesdk import ZBApiException, ZBApiUrl, ZBClientException, ZeroBounce

SECRET = "secret-key-123"


class _Offline(TestCase):
    """The offline suite's fake transport, without re-running that suite's tests."""

    def setUp(self):
        self.transport = offline.FakeTransport()
        patcher = patch("requests.sessions.Session.send", lambda session, request, **kw: self.transport(request, **kw))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = ZeroBounce("client-key")

    def _only(self):
        self.assertEqual(len(self.transport.requests), 1)
        return self.transport.requests[0]

    def _csv(self):
        path = Path(tempfile.mkdtemp()) / "rows.csv"
        path.write_text("email,name\nada@example.com,Ada\n")
        return path


class TransportFailureTest(TestCase):
    """A failed connection must not leak the API key through the exception message."""

    def setUp(self):
        def refuse(session, request, **kwargs):
            raise RequestsConnectionError(f"Max retries exceeded with url: {request.url}")

        patcher = patch("requests.sessions.Session.send", refuse)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_transport_redacts_the_key(self):
        client = ZeroBounce(SECRET)
        calls = [
            lambda: client.get_credits(),                                     # _get
            lambda: client.validate("a@b.com", use_post=True),                # _post_form
            lambda: client.add_filter("allow", "email", "a@b.com"),           # _request_json
            lambda: client.send_file_stream(BytesIO(b"a@b.com\n"), "a.csv", 1),  # _post
            lambda: client.get_file("file-9", str(Path(tempfile.mkdtemp()) / "never.csv")),  # _get_file download
            lambda: client.email_finder_get_file("file-9", str(Path(tempfile.mkdtemp()) / "n.csv")),  # bulk root download
            lambda: client.create_inbox_placement_test("Spring launch"),      # JSON body
        ]
        for call in calls:
            with self.assertRaises(RequestsConnectionError) as caught:
                call()
            self.assertNotIn(SECRET, str(caught.exception), call)

        # A GET carries the key in the URL that the error quotes: it is masked, not dropped.
        with self.assertRaises(RequestsConnectionError) as caught:
            client.get_credits()
        self.assertIn("api_key=***", str(caught.exception))


class ErrorBodyTest(_Offline):
    def _answer(self, status, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.transport._reply = lambda recorded: offline._response(status, body, content_type)

    def test_success_false_bodies_raise_their_message(self):
        cases = [
            ({"success": False, "message": ["File cannot be found."]}, "File cannot be found."),
            ({"success": "False", "error_message": "File cannot be found."}, "File cannot be found."),
            ({"success": "false", "message": []}, "Request failed"),
            ({"success": False, "message": "Error: Error: api_key is invalid"}, "Error: api_key is invalid"),
        ]
        for payload, expected in cases:
            self._answer(200, payload)
            with self.assertRaises(ZBApiException) as caught:
                self.client.file_status("file-9")
            self.assertEqual(str(caught.exception), expected, payload)

    def test_cloudflare_block_raises_its_title(self):
        self._answer(200, {"title": "Access denied | zerobounce.net used Cloudflare", "cloudflare_error": True})
        with self.assertRaises(ZBApiException) as caught:
            self.client.get_credits()
        self.assertIn("Access denied", str(caught.exception))

    def test_rate_limit_and_server_errors_are_short(self):
        for status, body, content_type in (
            (429, b"Too Many Requests", "text/plain"),
            (500, b"<html><head><title>500 Internal Server Error</title></head></html>", "text/html"),
            (400, json.dumps({"detail": [{"loc": ["body", "name"], "msg": "field required"}]}).encode(), "application/json"),
        ):
            self._answer(status, body, content_type)
            with self.assertRaises(ZBApiException) as caught:
                self.client.validate("a@b.com")
            self.assertLess(len(str(caught.exception)), 300)
            self.assertNotIn("<html", str(caught.exception).lower())

    def test_list_s3files_error_and_unexpected_shapes(self):
        self._answer(200, {"error": "Invalid API key"})
        with self.assertRaises(ZBApiException) as caught:
            self.client.list_s3files()
        self.assertEqual(str(caught.exception), "Invalid API key")
        self._answer(200, {"success": True})
        with self.assertRaises(ZBApiException):
            self.client.list_s3files()


class OptionalFieldsTest(_Offline):
    def test_send_file_sends_every_optional_field(self):
        for send in (
            lambda **kw: self.client.send_file(str(self._csv()), 1, **kw),
            lambda **kw: self.client.send_file_stream(BytesIO(b"a@b.com\n"), "a.csv", 1, **kw),
        ):
            self.transport.requests.clear()
            send(
                return_url="https://hooks.example.com/done",
                first_name_column=2,
                last_name_column=3,
                gender_column=4,
                ip_address_column=5,
                has_header_row=True,
                remove_duplicate=False,
                allow_phase_2=True,
            )
            form = self._only().form
            self.assertEqual(form["return_url"], "https://hooks.example.com/done")
            self.assertEqual(
                [form[k] for k in ("first_name_column", "last_name_column", "gender_column", "ip_address_column")],
                ["2", "3", "4", "5"],
            )
            self.assertEqual(form["has_header_row"], "true")
            self.assertEqual(form["remove_duplicate"], "false")
            self.assertEqual(form["allow_phase_2"], "true")

    def test_scoring_send_file_sends_return_url(self):
        self.client.scoring_send_file(str(self._csv()), 1, return_url="https://hooks.example.com/s")
        self.assertEqual(self._only().form["return_url"], "https://hooks.example.com/s")
        self.transport.requests.clear()
        self.client.scoring_send_file_stream(BytesIO(b"a@b.com\n"), "a.csv", 1, return_url="https://hooks.example.com/s")
        self.assertEqual(self._only().form["return_url"], "https://hooks.example.com/s")

    def test_email_finder_name_columns(self):
        self.client.send_email_finder_file(
            str(self._csv()), 1, first_name_column=2, last_name_column=3, middle_name_column=4, has_header_row=True
        )
        form = self._only().form
        self.assertEqual((form["first_name_column"], form["last_name_column"], form["middle_name_column"]), ("2", "3", "4"))
        self.assertNotIn("full_name_column", form)
        self.transport.requests.clear()
        self.client.send_email_finder_file_stream(BytesIO(b"x\n"), "f.csv", 1, full_name_column=2)
        form = self._only().form
        self.assertEqual(form["full_name_column"], "2")
        self.assertNotIn("first_name_column", form)

    def test_middle_name_is_sent(self):
        self.client.find_email_format("Ada", domain="example.com", middle_name="King", last_name="Lovelace")
        query = self._only().query
        self.assertEqual((query["middle_name"], query["last_name"]), ("King", "Lovelace"))

    def test_required_columns_reject_none(self):
        csv = str(self._csv())
        stream = BytesIO(b"x\n")
        for attempt in (
            lambda: self.client.send_email_finder_file(csv, None, first_name_column=2),
            lambda: self.client.send_email_finder_file_stream(stream, "f.csv", None, full_name_column=2),
            lambda: self.client.send_email_finder_file(csv, 1),
            lambda: self.client.send_email_finder_file_stream(stream, "f.csv", 1, last_name_column=3),
            lambda: self.client.send_domain_search_file(csv, None),
            lambda: self.client.send_domain_search_file_stream(stream, "d.csv", None),
            lambda: self.client.send_list_evaluator_file(csv, None),
            lambda: self.client.send_list_evaluator_file_stream(stream, "l.csv", None),
            lambda: self.client.score_s3file("  ", True),
            lambda: self.client.email_finder_get_file("  ", "out.csv"),
            lambda: self.client.domain_search_delete_file("  "),
        ):
            self.transport.requests.clear()
            with self.assertRaises(ZBClientException):
                attempt()
            self.assertEqual(self.transport.requests, [])

    def test_base_url_enum_and_bad_type(self):
        ZeroBounce("k", base_url=ZBApiUrl.API_EU_URL).get_credits()
        self.assertEqual(self._only().host, "api-eu.zerobounce.net")
        with self.assertRaises(ZBClientException):
            ZeroBounce("k", base_url=42)


class ResponseModelTest(TestCase):
    """Response shapes from the docs, including the ones that used to crash."""

    def test_lowercase_message_raises_api_error_not_key_error(self):
        from zerobouncesdk import ZBFindDomainResponse, ZBGuessFormatResponse

        for model in (ZBFindDomainResponse, ZBGuessFormatResponse):
            with self.assertRaises(ZBApiException) as caught:
                model({"message": "Invalid API key or your account ran out of credits"})
            self.assertIn("Invalid API key", str(caught.exception))
            with self.assertRaises(ZBApiException):
                model({"Message": "Invalid API key or your account ran out of credits"})

    def test_unknown_confidence_is_none_with_a_warning(self):
        from zerobouncesdk import ZBConfidence, ZBFindDomainResponse, ZBFindEmailFormatResponse

        with self.assertWarns(UserWarning):
            self.assertIsNone(ZBFindEmailFormatResponse({"email": "a@b.com", "email_confidence": "very-high"}).email_confidence)
        with self.assertWarns(UserWarning):
            self.assertIsNone(ZBFindDomainResponse({"domain": "b.com", "confidence": "very-high"}).confidence)
        self.assertEqual(ZBFindEmailFormatResponse({"email_confidence": "HIGH"}).email_confidence, ZBConfidence.high)

    def test_validate_flags_and_processed_at(self):
        from datetime import datetime

        from zerobouncesdk import ZBValidateResponse, ZBValidateSubStatus

        result = ZBValidateResponse(
            {
                "status": "valid",
                "sub_status": "ai_agent_mailbox",
                "free_email": "true",
                "mx_found": "false",
                "catchall_domain": False,
                "processed_at": "2026-10-23 10:11:12",
            }
        )
        self.assertIs(result.free_email, True)
        self.assertIs(result.mx_found, False)
        self.assertIs(result.catchall_domain, False)
        self.assertEqual(result.sub_status, ZBValidateSubStatus.ai_agent_mailbox)
        self.assertEqual(result.processed_at, datetime(2026, 10, 23, 10, 11, 12))
        self.assertEqual(
            ZBValidateResponse({"processed_at": "2026-10-23 10:11:12.033"}).processed_at.microsecond, 33000
        )
        with self.assertWarns(UserWarning):
            self.assertEqual(ZBValidateResponse({"processed_at": "yesterday"}).processed_at, "yesterday")

    def test_api_usage_dates_in_both_documented_formats(self):
        from datetime import date

        from zerobouncesdk import ZBGetApiUsageResponse

        for start, end in (("1/1/2023", "12/31/2023"), ("2023/01/01", "2023/12/31")):
            usage = ZBGetApiUsageResponse({"total": 1, "start_date": start, "end_date": end})
            self.assertEqual((usage.start_date, usage.end_date), (date(2023, 1, 1), date(2023, 12, 31)))
        self.assertEqual(ZBGetApiUsageResponse({"total": 0}).sub_status_alias_address, 0)
        self.assertEqual(ZBGetApiUsageResponse({"total": 0}).sub_status_leading_period_removed, 0)

    def test_activity_fields(self):
        from zerobouncesdk import ZBGetActivityResponse

        found = ZBGetActivityResponse({"found": True, "active_in_days": "30", "active_first_seen": "2026-05-19"})
        self.assertEqual((found.active_in_days, found.active_first_seen), ("30", "2026-05-19"))
        missing = ZBGetActivityResponse({"found": False})
        self.assertIsNone(missing.active_first_seen)


class DocumentedVariantsTest(_Offline):
    def test_post_variants_send_the_same_fields_as_a_form(self):
        from datetime import date

        calls = [
            (lambda: self.client.get_credits(use_post=True), "/v2/getcredits", {}),
            (lambda: self.client.get_api_usage(date(2026, 1, 1), date(2026, 1, 31), use_post=True), "/v2/getapiusage",
             {"start_date": "2026-01-01", "end_date": "2026-01-31"}),
            (lambda: self.client.get_activity("ada@example.com", use_post=True), "/v2/activity", {"email": "ada@example.com"}),
            (lambda: self.client.find_domain(domain="example.com", use_post=True), "/v2/guessformat", {"domain": "example.com"}),
            (lambda: self.client.find_email_format("Ada", domain="example.com", use_post=True), "/v2/guessformat",
             {"first_name": "Ada", "domain": "example.com"}),
        ]
        for call, path, fields in calls:
            self.transport.requests.clear()
            call()
            recorded = self._only()
            self.assertEqual((recorded.method, recorded.path), ("POST", path))
            self.assertEqual(recorded.form, {"api_key": "client-key", **fields})
            self.assertEqual(recorded.query, {})

    def test_find_email_format_without_a_name(self):
        self.client.find_email_format(domain="example.com")
        query = self._only().query
        self.assertNotIn("first_name", query)
        self.assertEqual(query["domain"], "example.com")

    def test_list_evaluator_results_are_a_model(self):
        payload = {
            "file_id": "ev-1", "status": "processing", "progress": 0, "invalid_percentage": 0,
            "catch_all_percentage": 0, "activity_data_percentage": 0, "abuse": False, "do_not_mail": False,
            "spam_trap": False, "total_risky_percentage": 0, "error_message": "",
        }
        self.transport._reply = lambda recorded: offline._response(201, json.dumps(payload).encode(), "application/json")
        sent = self.client.send_list_evaluator_file(str(self._csv()), 1)
        self.assertEqual((sent.file_id, sent.status, sent.progress), ("ev-1", "processing", 0))
        self.assertEqual(type(sent).__name__, "ZBListEvaluatorResponse")

        finished = {**payload, "status": "finished", "progress": 100, "invalid_percentage": 4.2, "abuse": True}
        self.transport._reply = lambda recorded: offline._response(200, json.dumps(finished).encode(), "application/json")
        result = self.client.get_list_evaluator_result("ev-1")
        self.assertEqual((result.status, result.invalid_percentage, result.abuse), ("finished", 4.2, True))

    def test_filter_and_inbox_test_names_are_checked(self):
        for attempt in (
            lambda: self.client.add_filter("deny", "domain", "example.com"),
            lambda: self.client.add_filter("block", "ip", "203.0.113.1"),
            lambda: self.client.delete_filter("allow", "url", "x"),
            lambda: self.client.create_inbox_placement_test("launch <b>"),
            lambda: self.client.create_inbox_placement_test("launch;drop"),
        ):
            self.transport.requests.clear()
            with self.assertRaises(ZBClientException):
                attempt()
            self.assertEqual(self.transport.requests, [])
        self.client.create_inbox_placement_test("Q4 (EU) - A/B test, v1.2 & 'final' \\ ok")
        self.assertEqual(self._only().json["name"], "Q4 (EU) - A/B test, v1.2 & 'final' \\ ok")
        self.transport.requests.clear()
        self.client.add_filter("block", "mx", "*.example.com")
        self.assertEqual(self._only().form["target"], "mx")


class LiveApiShapesTest(_Offline):
    """Shapes seen on the live API that the docs don't describe."""

    def test_a_json_list_error_reads_as_its_first_message(self):
        body = json.dumps(["In-progress tests cannot be deleted."]).encode()
        self.transport._reply = lambda recorded: offline._response(400, body, "application/json")
        with self.assertRaises(ZBApiException) as caught:
            self.client.delete_inbox_placement_test(38890)
        self.assertEqual(str(caught.exception), "In-progress tests cannot be deleted.")
        self.assertEqual(caught.exception.status_code, 400)

    def test_main_client_errors_carry_the_http_status(self):
        self.transport._reply = lambda recorded: offline._response(
            403, b"<html><title>Access denied | zerobounce.net</title></html>", "text/html")
        with self.assertRaises(ZBApiException) as caught:
            self.client.scoring_file_status("file-9")
        self.assertEqual(caught.exception.status_code, 403)


class SendEvaluatedFileTest(_Offline):
    def test_it_sends_the_evaluator_file_id_as_a_form_field(self):
        # The live API wants the evaluated list's file_id, not a new upload.
        self.client.send_evaluated_file("ev-1")
        recorded = self._only()
        self.assertEqual(recorded.path, "/v2/send-evaluated-file/")
        self.assertEqual(recorded.form, {"api_key": "client-key", "file_id": "ev-1"})
        self.assertEqual(recorded.files, {})
        self.transport.requests.clear()
        with self.assertRaises(ZBClientException):
            self.client.send_evaluated_file("  ")
        self.assertEqual(self.transport.requests, [])
