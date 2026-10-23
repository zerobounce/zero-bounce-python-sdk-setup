"""Offline API suite.

A fake ``requests`` transport records every call and answers without the network.
Error modes are selected by the API key prefix and follow the live API.
"""

import json
import random
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from email.parser import BytesParser
from email.policy import HTTP
from io import BytesIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from requests import Response

from zerobouncesdk import (
    ZBApiException,
    ZBClientException,
    ZBGetFileOptions,
    ZBValidateBatchElement,
    ZBValidateResponse,
    ZeroBounce,
)

_HTML_PAGE = (
    "<!DOCTYPE html><html><head><title>Access denied | zerobounce.net</title></head><body>"
    + ("Access denied. " * 4000)
    + "</body></html>"
)


class RecordedRequest:
    def __init__(self, method, url, body, headers):
        parsed = urlparse(url)
        self.method = method.upper()
        self.url = url
        self.host = parsed.hostname
        self.path = parsed.path
        self.query = {k: v[-1] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.body = body if isinstance(body, (bytes, bytearray)) else (body or "").encode()
        content_type = self.headers.get("content-type", "")
        self.json = None
        self.form = {}
        self.files = {}
        if "application/json" in content_type and self.body:
            self.json = json.loads(self.body.decode())
        elif "multipart/form-data" in content_type and self.body:
            self.form, self.files = _parse_multipart(content_type, self.body)
        elif self.body and "application/x-www-form-urlencoded" in content_type:
            self.form = {
                k: v[-1]
                for k, v in parse_qs(self.body.decode(), keep_blank_values=True).items()
            }
        elif self.body and self.body[:1] in (b"{", b"["):
            self.json = json.loads(self.body.decode())

    @property
    def api_key(self):
        bearer = self.headers.get("authorization", "")
        if bearer.startswith("Bearer "):
            return bearer[len("Bearer "):]
        if "api_key" in self.query:
            return self.query["api_key"]
        if self.json and isinstance(self.json, dict) and "api_key" in self.json:
            return self.json["api_key"]
        return self.form.get("api_key")

    def field(self, name):
        if name in self.query:
            return self.query[name]
        if self.json and isinstance(self.json, dict) and name in self.json:
            return self.json[name]
        if name in self.form:
            return self.form[name]
        return None

    def has_field(self, name):
        if name in self.query:
            return True
        if self.json and isinstance(self.json, dict) and name in self.json:
            return True
        return name in self.form


def _parse_multipart(content_type, body):
    raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    message = BytesParser(policy=HTTP).parsebytes(raw)
    form = {}
    files = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files[name] = {"filename": filename, "data": payload}
        else:
            form[name] = payload.decode()
    return form, files


class FakeTransport:
    def __init__(self):
        self.requests = []
        self._lock = threading.Lock()

    def send(self, session, request, **kwargs):
        time.sleep(random.uniform(0.005, 0.02))
        recorded = RecordedRequest(request.method, request.url, request.body, request.headers)
        with self._lock:
            self.requests.append(recorded)
        return self._reply(recorded)

    def _reply(self, recorded):
        key = recorded.api_key or ""
        if key.startswith("redirect-"):
            return _response(302, b"", "text/plain", headers={"Location": "https://evil.example/steal"})
        if key.startswith("denied-"):
            return _response(403, _HTML_PAGE.encode(), "text/html; charset=UTF-8")
        if key.startswith("html200-"):
            page = "<!DOCTYPE html><html><title>Not a file</title><body>not csv</body></html>"
            return _response(200, page.encode(), "text/html")
        if key.startswith("empty-"):
            return _response(200, b"", "text/plain")
        if key.startswith("malformed-"):
            return _response(200, b"this is not json {{{", "application/json")
        if key.startswith("invalid-") or key.startswith("nocredits-"):
            return self._account_error(recorded, key)
        if key.startswith("itemerr-") and recorded.path.endswith("/validatebatch"):
            payload = {
                "email_batch": [{"address": "good@example.com", "status": "valid"}],
                "errors": [{"email_address": "bad@example.com", "error": "Invalid email address"}],
            }
            return _response(200, json.dumps(payload).encode(), "application/json")
        if key.startswith("doubled-"):
            return _response(
                200,
                json.dumps({"error": "Error: Error: Invalid API key"}).encode(),
                "application/json",
            )
        return _response(200, json.dumps(self._success(recorded, key)).encode(), "application/json")

    def _account_error(self, recorded, key):
        no_credits = key.startswith("nocredits-")
        text = "Your account ran out of credits" if no_credits else "Invalid API key or your account ran out of credits"
        path = recorded.path
        if path.endswith("/getcredits"):
            return _response(200, b'{"Credits":"-1"}', "application/json")
        if path.endswith("/getapiusage") and not no_credits:
            return _response(200, b'{"error":"Invalid API key"}', "application/json")
        if path.endswith("/validatebatch"):
            payload = {
                "email_batch": [],
                "errors": [{"email_address": "all", "error": "Invalid API Key or your account ran out of credits"}],
            }
            return _response(200, json.dumps(payload).encode(), "application/json")
        if path.endswith("/getfile"):
            return _response(403, _HTML_PAGE.encode(), "text/html; charset=UTF-8")
        if path.endswith("/deletefile") or path.endswith("/filestatus") and "email-finder" in path or path.endswith("/filestatus") and "domain-search" in path:
            return _response(403, _HTML_PAGE.encode(), "text/html; charset=UTF-8")
        if path.endswith("/filestatus"):
            payload = {"success": "False", "message": ["api_key is invalid"]}
            return _response(401, json.dumps(payload).encode(), "application/json")
        if path.endswith("/sendfile") or path.rstrip("/").endswith("listevaluator") or "send-evaluated-file" in path:
            payload = {"success": "False", "message": ["api_key is invalid"]}
            return _response(401, json.dumps(payload).encode(), "application/json")
        if path.endswith("/listS3files") or "S3file" in path or path.rstrip("/").endswith("listevaluator") or "/listevaluator/" in path:
            payload = {"success": "False", "message": ["api_key is invalid"]}
            status = 401
            return _response(status, json.dumps(payload).encode(), "application/json")
        if "/api/ipt/" in path:
            return _response(401, json.dumps({"detail": "Invalid API key."}).encode(), "application/json")
        if "/filters/" in path:
            payload = {"Error": text}
            return _response(200, json.dumps(payload).encode(), "application/json")
        if path.endswith("/guessformat"):
            return _response(200, json.dumps({"Message": text}).encode(), "application/json")
        return _response(200, json.dumps({"error": text}).encode(), "application/json")

    def _success(self, recorded, key):
        path = recorded.path
        echo = {"echo_key": key}
        if path.endswith("/getfile"):
            # Replaced below with CSV bytes. Marker keeps the branch obvious.
            return {"__csv__": key}
        if path.endswith("/getcredits"):
            return {"Credits": key}
        if path.endswith("/getapiusage"):
            return {"total": 1, "start_date": "1/1/2024", "end_date": "1/2/2024", **echo}
        if path.endswith("/activity"):
            return {"found": True, "active_in_days": "30", **echo}
        if path.endswith("/scoring"):
            return {"email": recorded.field("email"), "score": 9, **echo}
        if path.endswith("/validate"):
            return {"address": recorded.field("email"), "status": "valid", **echo}
        if path.endswith("/validatebatch"):
            return {
                "email_batch": [{"address": "a@b.com", "status": "valid", "echo_key": key}],
                "errors": [],
            }
        if path.endswith("/filestatus"):
            return {
                "success": True,
                "file_id": recorded.field("file_id"),
                "file_name": "emails.csv",
                "upload_date": "2023-03-28T12:30:18Z",
                "file_status": "Complete",
                "complete_percentage": "100%",
                **echo,
            }
        if path.endswith("/deletefile"):
            return {"success": True, "message": "File Deleted", "file_id": recorded.field("file_id"), "file_name": "emails.csv", **echo}
        if path.endswith("/sendfile") or "listevaluator" in path or "send-evaluated-file" in path or path.endswith("S3file") or path.endswith("SFTPfile"):
            return {"success": True, "message": "File Accepted", "file_id": "file-1", "file_name": "emails.csv", **echo}
        if path.endswith("/guessformat"):
            return {
                "email": "ada@example.com",
                "domain": recorded.field("domain") or "example.com",
                "company_name": recorded.field("company_name") or "",
                "format": "first",
                "status": "valid",
                "sub_status": "",
                "confidence": "high",
                "email_confidence": "high",
                "did_you_mean": "",
                "failure_reason": "",
                "other_domain_formats": [],
                **echo,
            }
        if "/filters/" in path:
            return {"Message": "Filter successfully added", **echo}
        if path.endswith("/listS3files") and key.startswith("s3files-"):
            files = [{"Name": "uploads/a.csv", "Size": 100, "LastModified": "Mon, 08 May 2023 00:00:01 GMT"}]
            return {"success": True, "files": files}
        if path.endswith("/listS3files"):
            return [{"name": "uploads/a.csv", "echo_key": key}]
        if "/listevaluator/" in path:
            return {"file_status": "Complete", **echo}
        return {"ok": True, **echo}

    def __call__(self, request, **kwargs):
        reply = self.send(None, request, **kwargs)
        # getfile success is CSV, not the JSON marker.
        if reply.headers.get("Content-Type", "").startswith("application/json"):
            try:
                payload = json.loads(reply.content.decode())
            except ValueError:
                return reply
            if isinstance(payload, dict) and "__csv__" in payload:
                key = payload["__csv__"]
                return _response(200, f"email\n{key}\n".encode(), "text/csv")
        return reply


def _response(status, body, content_type, headers=None):
    response = Response()
    response.status_code = status
    response._content = body
    response.headers["Content-Type"] = content_type
    response.encoding = "utf-8"
    response.url = "https://api.zerobounce.net/v2/unused"
    if headers:
        for name, value in headers.items():
            response.headers[name] = value
    return response


class OfflineApiTest(TestCase):
    def setUp(self):
        self.transport = FakeTransport()

        def send(session, request, **kwargs):
            return self.transport(request, **kwargs)

        self._patch = patch("requests.sessions.Session.send", send)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.client = ZeroBounce("client-key")

    def _only(self):
        self.assertEqual(len(self.transport.requests), 1)
        return self.transport.requests[0]

    def _csv(self, name="rows.csv"):
        path = Path(tempfile.mkdtemp()) / name
        path.write_text("email,name\nada@example.com,Ada\n")
        return path

    def test_every_public_method_hits_the_right_endpoint(self):
        csv = self._csv()
        stream = BytesIO(b"email\nada@example.com\n")
        out = Path(tempfile.mkdtemp()) / "out.csv"
        cases = [
            ("get_credits", lambda: self.client.get_credits(), "GET", "api.zerobounce.net", "/v2/getcredits"),
            ("get_api_usage", lambda: self.client.get_api_usage(date(2024, 1, 2), date(2024, 1, 3)), "GET", "api.zerobounce.net", "/v2/getapiusage"),
            ("get_activity", lambda: self.client.get_activity("ada@example.com"), "GET", "api.zerobounce.net", "/v2/activity"),
            ("score_email", lambda: self.client.score_email("ada@example.com"), "GET", "api.zerobounce.net", "/v2/scoring"),
            ("score_email_post", lambda: self.client.score_email("ada@example.com", use_post=True), "POST", "api.zerobounce.net", "/v2/scoring"),
            ("validate", lambda: self.client.validate("ada@example.com"), "GET", "api.zerobounce.net", "/v2/validate"),
            ("validate_post", lambda: self.client.validate("ada@example.com", use_post=True), "POST", "api.zerobounce.net", "/v2/validate"),
            ("validate_batch", lambda: self.client.validate_batch([ZBValidateBatchElement("ada@example.com", "1.2.3.4")]), "POST", "api.zerobounce.net", "/v2/validatebatch"),
            ("send_file", lambda: self.client.send_file(str(csv), 1), "POST", "bulkapi.zerobounce.net", "/v2/sendfile"),
            ("send_file_stream", lambda: self.client.send_file_stream(BytesIO(b"a@b.com\n"), "a.csv", 1), "POST", "bulkapi.zerobounce.net", "/v2/sendfile"),
            ("scoring_send_file", lambda: self.client.scoring_send_file(str(csv), 1), "POST", "bulkapi.zerobounce.net", "/v2/scoring/sendfile"),
            ("scoring_send_file_stream", lambda: self.client.scoring_send_file_stream(stream, "a.csv", 1), "POST", "bulkapi.zerobounce.net", "/v2/scoring/sendfile"),
            ("file_status", lambda: self.client.file_status("file-9"), "GET", "bulkapi.zerobounce.net", "/v2/filestatus"),
            ("scoring_file_status", lambda: self.client.scoring_file_status("file-9"), "GET", "bulkapi.zerobounce.net", "/v2/scoring/filestatus"),
            ("get_file", lambda: self.client.get_file("file-9", str(out)), "GET", "bulkapi.zerobounce.net", "/v2/getfile"),
            ("scoring_get_file", lambda: self.client.scoring_get_file("file-9", str(out) + ".score"), "GET", "bulkapi.zerobounce.net", "/v2/scoring/getfile"),
            ("delete_file", lambda: self.client.delete_file("file-9"), "GET", "bulkapi.zerobounce.net", "/v2/deletefile"),
            ("scoring_delete_file", lambda: self.client.scoring_delete_file("file-9"), "GET", "bulkapi.zerobounce.net", "/v2/scoring/deletefile"),
            ("send_email_finder_file", lambda: self.client.send_email_finder_file(str(csv), 1, first_name_column=2), "POST", "bulkapi.zerobounce.net", "/email-finder/sendfile"),
            ("send_email_finder_file_stream", lambda: self.client.send_email_finder_file_stream(BytesIO(b"example.com\n"), "f.csv", 1, full_name_column=2), "POST", "bulkapi.zerobounce.net", "/email-finder/sendfile"),
            ("email_finder_file_status", lambda: self.client.email_finder_file_status("file-9"), "GET", "bulkapi.zerobounce.net", "/email-finder/filestatus"),
            ("email_finder_get_file", lambda: self.client.email_finder_get_file("file-9", str(out) + ".finder"), "GET", "bulkapi.zerobounce.net", "/email-finder/getfile"),
            ("email_finder_delete_file", lambda: self.client.email_finder_delete_file("file-9"), "GET", "bulkapi.zerobounce.net", "/email-finder/deletefile"),
            ("send_domain_search_file", lambda: self.client.send_domain_search_file(str(csv), 1), "POST", "bulkapi.zerobounce.net", "/domain-search/sendfile"),
            ("send_domain_search_file_stream", lambda: self.client.send_domain_search_file_stream(BytesIO(b"example.com\n"), "d.csv", 1), "POST", "bulkapi.zerobounce.net", "/domain-search/sendfile"),
            ("domain_search_file_status", lambda: self.client.domain_search_file_status("file-9"), "GET", "bulkapi.zerobounce.net", "/domain-search/filestatus"),
            ("domain_search_get_file", lambda: self.client.domain_search_get_file("file-9", str(out) + ".domain"), "GET", "bulkapi.zerobounce.net", "/domain-search/getfile"),
            ("domain_search_delete_file", lambda: self.client.domain_search_delete_file("file-9"), "GET", "bulkapi.zerobounce.net", "/domain-search/deletefile"),
            ("send_list_evaluator_file", lambda: self.client.send_list_evaluator_file(str(csv), 1), "POST", "bulkapi.zerobounce.net", "/v2/listevaluator/"),
            ("send_list_evaluator_file_stream", lambda: self.client.send_list_evaluator_file_stream(BytesIO(b"a@b.com\n"), "l.csv", 1), "POST", "bulkapi.zerobounce.net", "/v2/listevaluator/"),
            ("get_list_evaluator_result", lambda: self.client.get_list_evaluator_result("file-9"), "GET", "bulkapi.zerobounce.net", "/v2/listevaluator/file-9/"),
            ("send_evaluated_file", lambda: self.client.send_evaluated_file("file-9"), "POST", "bulkapi.zerobounce.net", "/v2/send-evaluated-file/"),
            ("add_filter", lambda: self.client.add_filter("allow", "domain", "example.com"), "POST", "api.zerobounce.net", "/v2/filters/add"),
            ("list_filters", lambda: self.client.list_filters(), "GET", "api.zerobounce.net", "/v2/filters/list"),
            ("list_filters_post", lambda: self.client.list_filters(use_post=True), "POST", "api.zerobounce.net", "/v2/filters/list"),
            ("delete_filter", lambda: self.client.delete_filter("allow", "domain", "example.com"), "POST", "api.zerobounce.net", "/v2/filters/delete"),
            ("list_s3files", lambda: self.client.list_s3files(bucket="b", search="a"), "GET", "bulkapi.zerobounce.net", "/listS3files"),
            ("validate_s3file", lambda: self.client.validate_s3file("lists/jan.csv", True, return_url="https://example.com/cb"), "POST", "bulkapi.zerobounce.net", "/validateS3file"),
            ("score_s3file", lambda: self.client.score_s3file("lists/jan.csv", True, return_url="https://example.com/cb"), "POST", "bulkapi.zerobounce.net", "/scoreS3file"),
            ("export_s3file", lambda: self.client.export_s3file("file-9", "export-bucket"), "POST", "bulkapi.zerobounce.net", "/exportS3file"),
            ("email_finder_s3file", lambda: self.client.email_finder_s3file("lists/people.csv", True, return_url="https://example.com/cb"), "POST", "bulkapi.zerobounce.net", "/emailFinderS3file"),
            ("domain_search_s3file", lambda: self.client.domain_search_s3file("lists/domains.csv", True, return_url="https://example.com/cb"), "POST", "bulkapi.zerobounce.net", "/domainSearchS3file"),
            ("validate_sftpfile", lambda: self.client.validate_sftpfile("my_file.txt", True, return_url="https://example.com/cb"), "POST", "bulkapi.zerobounce.net", "/validateSFTPfile"),
            ("score_sftpfile", lambda: self.client.score_sftpfile("my_file.txt", True, return_url="https://example.com/cb"), "POST", "bulkapi.zerobounce.net", "/scoreSFTPfile"),
            ("email_finder_sftpfile", lambda: self.client.email_finder_sftpfile("my_file.txt", True, return_url="https://example.com/cb"), "POST", "bulkapi.zerobounce.net", "/emailFinderSFTPfile"),
            ("domain_search_sftpfile", lambda: self.client.domain_search_sftpfile("my_file.txt", True, return_url="https://example.com/cb"), "POST", "bulkapi.zerobounce.net", "/domainSearchSFTPfile"),
            ("export_sftpfile", lambda: self.client.export_sftpfile("file-9"), "POST", "bulkapi.zerobounce.net", "/exportSFTPfile"),
            ("guess_format", lambda: self.client.guess_format("example.com", first_name="Ada"), "GET", "api.zerobounce.net", "/v2/guessformat"),
            ("find_email_format", lambda: self.client.find_email_format("Ada", domain="example.com"), "GET", "api.zerobounce.net", "/v2/guessformat"),
            ("find_domain", lambda: self.client.find_domain(domain="example.com"), "GET", "api.zerobounce.net", "/v2/guessformat"),
            ("get_inbox_placement_providers", lambda: self.client.get_inbox_placement_providers(), "GET", "bulkapi.zerobounce.net", "/api/ipt/providers"),
            ("get_inbox_placement_test_types", lambda: self.client.get_inbox_placement_test_types(), "GET", "bulkapi.zerobounce.net", "/api/ipt/test-types"),
            ("create_inbox_placement_test", lambda: self.client.create_inbox_placement_test("Spring launch"), "POST", "bulkapi.zerobounce.net", "/api/ipt/test"),
            ("get_inbox_placement_test", lambda: self.client.get_inbox_placement_test(42), "GET", "bulkapi.zerobounce.net", "/api/ipt/test/42"),
            ("list_inbox_placement_tests", lambda: self.client.list_inbox_placement_tests(), "GET", "bulkapi.zerobounce.net", "/api/ipt/tests"),
            ("delete_inbox_placement_test", lambda: self.client.delete_inbox_placement_test("42"), "DELETE", "bulkapi.zerobounce.net", "/api/ipt/test/42"),
            ("get_inbox_placement_webhook", lambda: self.client.get_inbox_placement_webhook(), "GET", "bulkapi.zerobounce.net", "/api/ipt/webhook"),
            ("set_inbox_placement_webhook", lambda: self.client.set_inbox_placement_webhook("https://hooks.example.com/ipt"), "PUT", "bulkapi.zerobounce.net", "/api/ipt/webhook"),
        ]
        for name, call, method, host, path in cases:
            self.transport.requests.clear()
            call()
            recorded = self._only()
            self.assertEqual(recorded.method, method, name)
            self.assertEqual(recorded.host, host, name)
            self.assertEqual(recorded.path, path, name)
            self.assertEqual(recorded.api_key, "client-key", name)

    def test_validate_batch_posts_json_to_the_api_host(self):
        self.client.validate_batch(
            [ZBValidateBatchElement("ada@example.com", "0.0.0.0")],
            timeout=30,
            activity_data=False,
            verify_plus=True,
        )
        recorded = self._only()
        self.assertNotIn("bulkapi", recorded.host)
        batch = recorded.json["email_batch"]
        self.assertEqual(batch[0]["email_address"], "ada@example.com")
        self.assertEqual(batch[0]["ip_address"], "0.0.0.0")
        # A string: the live API rejects the batch when timeout is a JSON number.
        self.assertEqual(recorded.json["timeout"], "30")
        self.assertIs(recorded.json["activity_data"], False)
        self.assertIs(recorded.json["verify_plus"], True)

    def test_optional_parameters_are_omitted_until_set(self):
        self.client.validate("ada@example.com")
        recorded = self._only()
        self.assertEqual(recorded.query["email"], "ada@example.com")
        for name in ("ip_address", "timeout", "activity_data", "verify_plus"):
            self.assertNotIn(name, recorded.query)
        self.transport.requests.clear()
        self.client.validate(
            "ada@example.com",
            ip_address="203.0.113.8",
            timeout=10,
            activity_data=False,
            verify_plus=False,
        )
        recorded = self._only()
        self.assertEqual(recorded.query["ip_address"], "203.0.113.8")
        self.assertEqual(recorded.query["timeout"], "10")
        self.assertEqual(recorded.query["activity_data"], "false")
        self.assertEqual(recorded.query["verify_plus"], "false")

    def test_validate_domain_info_and_greylist_options(self):
        self.client.validate("ada@example.com")
        recorded = self._only()
        for name in ("domain_info", "greylist_processing", "callback_url"):
            self.assertNotIn(name, recorded.query)

        self.transport.requests.clear()
        self.client.validate("ada@example.com", domain_info=True, greylist_processing=False)
        recorded = self._only()
        self.assertEqual(recorded.query["domain_info"], "true")
        self.assertEqual(recorded.query["greylist_processing"], "false")
        self.assertNotIn("callback_url", recorded.query)

        self.transport.requests.clear()
        self.client.validate(
            "ada@example.com",
            greylist_processing=True,
            callback_url="https://hooks.example.com/zb?x=1",
            use_post=True,
        )
        recorded = self._only()
        self.assertEqual(recorded.form["greylist_processing"], "true")
        self.assertEqual(recorded.form["callback_url"], "https://hooks.example.com/zb?x=1")

    def test_validate_response_reads_domain_info_and_greylist_message(self):
        result = ZBValidateResponse(
            {
                "address": "ada@example.com",
                "status": "valid",
                "domain_website_exists": "True",
                "domain_registrant_company_name": "Example Inc",
            }
        )
        self.assertEqual(result.domain_website_exists, "True")
        self.assertEqual(result.domain_registrant_company_name, "Example Inc")
        self.assertIsNone(result.message)

        pending = ZBValidateResponse({"Message": "Greylist validation still in progress. Please try again later."})
        self.assertIsNone(pending.status)
        self.assertIn("still in progress", pending.message)

    def test_list_evaluator_base_url_is_separate_and_file_id_is_encoded(self):
        client = ZeroBounce("client-key")
        client.LIST_EVALUATOR_BASE_URL = "https://test-members-api.zerobounce.net/api/validation/list-evaluator"
        client.get_list_evaluator_result("a/b?c")
        recorded = self._only()
        self.assertEqual(recorded.host, "test-members-api.zerobounce.net")
        self.assertIn("/api/validation/list-evaluator/a%2Fb%3Fc/", recorded.url)

        self.transport.requests.clear()
        client.send_evaluated_file("ev-1")
        self.assertEqual(self._only().path, "/v2/send-evaluated-file/")

    def test_inbox_placement_create_sends_camel_case_json(self):
        self.client.create_inbox_placement_test("Spring launch")
        recorded = self._only()
        self.assertEqual(recorded.json, {"name": "Spring launch"})
        # The documented Authorization header, so the key stays out of the URL.
        self.assertEqual(recorded.headers["authorization"], "Bearer client-key")
        self.assertNotIn("client-key", recorded.url)

        self.transport.requests.clear()
        self.client.create_inbox_placement_test(
            "From match",
            test_type=1,
            sender_email="news@example.com",
            provider_ids=[1, 2],
            seed_ids=[7],
            providers=[{"id": 1, "maxSeeds": 3}],
            webhook_url="https://hooks.example.com/ipt",
        )
        self.assertEqual(
            self._only().json,
            {
                "name": "From match",
                "testType": 1,
                "senderEmail": "news@example.com",
                "providerIds": [1, 2],
                "seedIds": [7],
                "providers": [{"id": 1, "maxSeeds": 3}],
                "webhookUrl": "https://hooks.example.com/ipt",
            },
        )

        self.transport.requests.clear()
        self.client.set_inbox_placement_webhook("https://hooks.example.com/ipt")
        self.assertEqual(self._only().json, {"webhookUrl": "https://hooks.example.com/ipt"})

    def test_inbox_placement_list_filters(self):
        self.client.list_inbox_placement_tests()
        self.assertEqual(self._only().query, {})

        self.transport.requests.clear()
        self.client.list_inbox_placement_tests(
            status="finished",
            created_after=date(2026, 10, 1),
            created_before="2026-10-23T00:00:00Z",
            page=2,
            page_size=100,
        )
        recorded = self._only()
        self.assertEqual(recorded.query["status"], "finished")
        self.assertEqual(recorded.query["createdAfter"], "2026-10-01")
        self.assertEqual(recorded.query["createdBefore"], "2026-10-23T00:00:00Z")
        self.assertEqual(recorded.query["page"], "2")
        self.assertEqual(recorded.query["page_size"], "100")

    def test_s3_and_sftp_file_jobs_send_the_documented_fields(self):
        self.client.email_finder_s3file("lists/people.csv", False, return_url="https://example.com/cb")
        recorded = self._only()
        self.assertEqual(
            recorded.form,
            {"api_key": "client-key", "file_name": "lists/people.csv", "has_header_row": "false",
             "return_url": "https://example.com/cb"},
        )

        self.transport.requests.clear()
        self.client.domain_search_sftpfile("my_file.txt", True, remove_duplicates=False, return_url="https://hooks.example.com/done")
        recorded = self._only()
        self.assertEqual(recorded.form["has_header_row"], "true")
        self.assertEqual(recorded.form["remove_duplicates"], "false")
        self.assertEqual(recorded.form["return_url"], "https://hooks.example.com/done")
        self.assertNotIn("remove_duplicate", recorded.form)

        # The live API rejects these jobs without return_url, and validateSFTPfile without file_name.
        for attempt in (
            lambda: self.client.validate_sftpfile(None, True, return_url="https://example.com/cb"),
            lambda: self.client.validate_s3file("lists/jan.csv", True),
            lambda: self.client.score_sftpfile("my_file.txt", True, return_url=" "),
        ):
            self.transport.requests.clear()
            with self.assertRaises(ZBClientException):
                attempt()
            self.assertEqual(self.transport.requests, [])

        self.transport.requests.clear()
        self.client.score_s3file("lists/jan.csv", has_header_row=True, return_url="https://hooks.example.com/s")
        self.assertEqual(self._only().form["return_url"], "https://hooks.example.com/s")

        self.transport.requests.clear()
        self.client.export_s3file("file-9")
        self.assertEqual(self._only().form, {"api_key": "client-key", "file_id": "file-9"})

        self.transport.requests.clear()
        self.client.export_sftpfile("file-9", export_path="/exports")
        self.assertEqual(self._only().form["export_path"], "/exports")

    def test_list_s3files_reads_the_documented_files_object(self):
        files = ZeroBounce("s3files-key").list_s3files()
        self.assertEqual(files[0]["Name"], "uploads/a.csv")
        self.assertEqual(self.client.list_s3files()[0]["name"], "uploads/a.csv")

    def test_query_values_are_percent_encoded(self):
        client = ZeroBounce("key with space&plus")
        client.validate("a b@ex.com")
        recorded = self._only()
        self.assertNotIn(" ", recorded.url)
        self.assertIn("key+with+space%26plus", recorded.url)
        self.assertIn("a+b%40ex.com", recorded.url)
        self.assertEqual(recorded.api_key, "key with space&plus")
        self.assertEqual(recorded.query["email"], "a b@ex.com")

    def test_column_zero_is_sent_and_unset_columns_are_left_out(self):
        csv = self._csv()
        self.client.send_file(str(csv), 0, first_name_column=0, has_header_row=False, remove_duplicate=False)
        recorded = self._only()
        self.assertEqual(recorded.form["email_address_column"], "0")
        self.assertEqual(recorded.form["first_name_column"], "0")
        self.assertNotIn("last_name_column", recorded.form)
        self.assertNotIn("gender_column", recorded.form)
        self.assertNotIn("ip_address_column", recorded.form)
        self.assertNotIn("allow_phase_2", recorded.form)
        self.assertEqual(recorded.form["has_header_row"], "false")
        self.assertEqual(recorded.form["remove_duplicate"], "false")

        self.transport.requests.clear()
        self.client.send_email_finder_file(str(csv), 0, full_name_column=0, has_header_row=False)
        recorded = self._only()
        self.assertEqual(recorded.form["domain_column"], "0")
        self.assertEqual(recorded.form["full_name_column"], "0")
        self.assertEqual(recorded.form["has_header_row"], "false")
        self.assertNotIn("first_name_column", recorded.form)

        self.transport.requests.clear()
        self.client.send_domain_search_file(str(csv), 0, has_header_row=False)
        self.assertEqual(self._only().form["has_header_row"], "false")

        self.transport.requests.clear()
        self.client.send_list_evaluator_file(str(csv), 0)
        self.assertEqual(self._only().form["email_address_column"], "0")

        self.transport.requests.clear()
        self.client.validate_s3file("a.csv", False, remove_duplicates=False, return_url="https://example.com/cb")
        self.assertEqual(
            self._only().form,
            {"api_key": "client-key", "file_name": "a.csv", "has_header_row": "false", "remove_duplicates": "false",
             "return_url": "https://example.com/cb"},
        )

        self.transport.requests.clear()
        self.client.scoring_send_file(str(csv), 1, has_header_row=True, remove_duplicate=True)
        recorded = self._only()
        self.assertEqual(recorded.form["has_header_row"], "true")
        self.assertEqual(recorded.form["remove_duplicate"], "true")
        self.assertNotIn("allow_phase_2", recorded.form)

    def test_get_file_options_and_scoring_omits_activity_data(self):
        out = Path(tempfile.mkdtemp()) / "out.csv"
        self.client.get_file("file-9", str(out), ZBGetFileOptions(download_type="phase_1", activity_data=False))
        recorded = self._only()
        self.assertEqual(recorded.query["download_type"], "phase_1")
        self.assertEqual(recorded.query["activity_data"], "false")
        self.assertIn("client-key", out.read_text())

        self.transport.requests.clear()
        self.client.scoring_get_file("file-9", str(out) + ".s", ZBGetFileOptions(download_type="combined", activity_data=True))
        recorded = self._only()
        self.assertEqual(recorded.query["download_type"], "combined")
        self.assertNotIn("activity_data", recorded.query)

    def test_invalid_arguments_send_no_request(self):
        csv = self._csv()
        attempts = [
            lambda: ZeroBounce("   "),
            lambda: ZeroBounce("k", base_url="http://evil.example/v2"),
            lambda: self.client.validate("a@b.com", timeout=2),
            lambda: self.client.validate("a@b.com", timeout=61),
            lambda: self.client.validate_batch([]),
            lambda: self.client.validate_batch([ZBValidateBatchElement("a@b.com")], timeout=9),
            lambda: ZBValidateBatchElement("  "),
            lambda: self.client.file_status("  "),
            lambda: self.client.get_file("  ", "out.csv"),
            lambda: self.client.delete_file("  "),
            lambda: self.client.find_email_format("Ada"),
            lambda: self.client.find_email_format("Ada", domain="example.com", company_name="Acme"),
            lambda: self.client.find_domain(),
            lambda: self.client.find_domain(domain="example.com", company_name="Acme"),
            lambda: self.client.add_filter("", "domain", "example.com"),
            lambda: self.client.delete_filter("allow", "", "example.com"),
            lambda: self.client.validate_s3file("  ", True, return_url="https://example.com/cb"),
            lambda: self.client.validate_s3file("lists/jan.csv", None),
            lambda: self.client.score_s3file("lists/jan.csv", None),
            lambda: self.client.export_s3file("  ", "bucket"),
            lambda: self.client.export_s3file("file-9", "  "),
            lambda: self.client.email_finder_s3file("  ", True, return_url="https://example.com/cb"),
            lambda: self.client.domain_search_s3file("lists/d.csv", None),
            lambda: self.client.score_sftpfile(None, True),
            lambda: self.client.validate_sftpfile("  ", True, return_url="https://example.com/cb"),
            lambda: self.client.email_finder_sftpfile("f.txt", None),
            lambda: self.client.export_sftpfile("  "),
            lambda: self.client.export_sftpfile("file-9", " "),
            lambda: self.client.get_list_evaluator_result("  "),
            lambda: self.client.email_finder_file_status("  "),
            lambda: self.client.validate("a@b.com", callback_url="https://hooks.example.com/zb"),
            lambda: self.client.validate("a@b.com", greylist_processing=True, callback_url="  "),
            lambda: self.client.create_inbox_placement_test("  "),
            lambda: self.client.create_inbox_placement_test("x" * 65),
            lambda: self.client.create_inbox_placement_test("t", test_type=4),
            lambda: self.client.create_inbox_placement_test("t", test_type=1),
            lambda: self.client.create_inbox_placement_test("t", providers=[{"maxSeeds": 2}]),
            lambda: self.client.create_inbox_placement_test("t", providers=[{"id": 1, "maxSeeds": 0}]),
            lambda: self.client.get_inbox_placement_test("  "),
            lambda: self.client.get_inbox_placement_test(None),
            lambda: self.client.delete_inbox_placement_test(""),
            lambda: self.client.list_inbox_placement_tests(status="pending"),
            lambda: self.client.list_inbox_placement_tests(page=0),
            lambda: self.client.list_inbox_placement_tests(page_size=101),
            lambda: self.client.set_inbox_placement_webhook(" "),
        ]
        for attempt in attempts:
            self.transport.requests.clear()
            with self.assertRaises((ZBClientException, ZBApiException)):
                attempt()
            self.assertEqual(self.transport.requests, [], attempt)

    def test_account_errors_raise_a_short_message(self):
        csv = self._csv()
        out = Path(tempfile.mkdtemp()) / "out.csv"
        client = ZeroBounce("invalid-key")
        credits = client.get_credits()
        self.assertEqual(credits.credits, "-1")

        raised = [
            lambda: client.get_api_usage(date(2024, 1, 1), date(2024, 1, 2)),
            lambda: client.get_activity("a@b.com"),
            lambda: client.score_email("a@b.com"),
            lambda: client.score_email("a@b.com", use_post=True),
            lambda: client.validate("a@b.com"),
            lambda: client.validate("a@b.com", use_post=True),
            lambda: client.validate_batch([ZBValidateBatchElement("a@b.com")]),
            lambda: client.file_status("file-9"),
            lambda: client.get_file("file-9", str(out)),
            lambda: client.delete_file("file-9"),
            lambda: client.send_file(str(csv), 1),
            lambda: client.list_filters(),
            lambda: client.add_filter("block", "domain", "x.com"),
            lambda: client.list_s3files(),
            lambda: client.email_finder_s3file("lists/people.csv", True, return_url="https://example.com/cb"),
            lambda: client.validate_sftpfile("my_file.txt", True, return_url="https://example.com/cb"),
            lambda: client.export_sftpfile("file-9"),
            lambda: client.find_email_format("Ada", domain="example.com"),
            lambda: client.find_domain(domain="example.com"),
            lambda: client.guess_format("example.com"),
            lambda: client.get_list_evaluator_result("file-9"),
            lambda: client.email_finder_file_status("file-9"),
            lambda: client.email_finder_get_file("file-9", str(out) + ".f"),
            lambda: client.domain_search_get_file("file-9", str(out) + ".d"),
            lambda: client.get_inbox_placement_providers(),
            lambda: client.create_inbox_placement_test("Spring launch"),
            lambda: client.get_inbox_placement_test(42),
            lambda: client.delete_inbox_placement_test(42),
            lambda: ZeroBounce("nocredits-key").validate("a@b.com"),
        ]
        for call in raised:
            with self.assertRaises(ZBApiException) as caught:
                call()
            message = str(caught.exception)
            self.assertGreater(len(message), 0, call)
            self.assertLess(len(message), 300, call)
            lowered = message.lower()
            self.assertNotIn("<html", lowered, call)
            self.assertNotIn("<!doctype", lowered, call)
            self.assertNotIn("error: error:", lowered, call)
            self.assertNotRegex(message, r"\[json.exception")

        with self.assertRaises(ZBApiException) as caught:
            client.validate_batch([ZBValidateBatchElement("a@b.com")])
        self.assertIn("Invalid API Key", str(caught.exception))

        with self.assertRaises(ZBApiException) as caught:
            client.get_inbox_placement_webhook()
        self.assertEqual(str(caught.exception), "Invalid API key.")

        with self.assertRaises(ZBApiException) as caught:
            client.list_s3files()
        self.assertEqual(str(caught.exception), "api_key is invalid")

        with self.assertRaises(ZBApiException) as caught:
            client.get_file("file-9", str(out))
        self.assertEqual(str(caught.exception), "Access denied")
        self.assertFalse(out.exists() and "DOCTYPE" in out.read_text(errors="replace"))

    def test_per_item_batch_errors_stay_on_the_result(self):
        client = ZeroBounce("itemerr-key")
        response = client.validate_batch([ZBValidateBatchElement("bad@example.com"), ZBValidateBatchElement("good@example.com")])
        self.assertEqual(len(response.email_batch), 1)
        self.assertEqual(response.errors[0].email_address, "bad@example.com")
        self.assertEqual(response.errors[0].error, "Invalid email address")

    def test_html_empty_and_malformed_bodies_are_short_errors(self):
        out = Path(tempfile.mkdtemp()) / "out.csv"
        for key in ("denied-key", "html200-key", "empty-key", "malformed-key"):
            client = ZeroBounce(key)
            for call in (
                lambda: client.validate("a@b.com"),
                lambda: client.validate_batch([ZBValidateBatchElement("a@b.com")]),
                lambda: client.get_file("file-9", str(out)),
                lambda: client.delete_file("file-9"),
            ):
                with self.assertRaises(ZBApiException) as caught:
                    call()
                message = str(caught.exception)
                self.assertLess(len(message), 300, (key, message[:80]))
                self.assertNotIn("<html", message.lower())
                self.assertNotIn("this is not json", message)
                self.assertNotIn("not csv", message)
        self.assertFalse(out.exists())

        with self.assertRaises(ZBApiException) as caught:
            ZeroBounce("denied-key").get_file("file-9", str(out))
        self.assertEqual(str(caught.exception), "Access denied")

        with self.assertRaises(ZBApiException) as caught:
            ZeroBounce("html200-key").validate("a@b.com")
        self.assertIn("HTML", str(caught.exception))

        with self.assertRaises(ZBApiException) as caught:
            ZeroBounce("empty-key").score_email("a@b.com")
        self.assertIn("Empty", str(caught.exception))

        with self.assertRaises(ZBApiException) as caught:
            ZeroBounce("malformed-key").get_credits()
        self.assertIn("JSON", str(caught.exception))

    def test_doubled_error_prefix_is_collapsed(self):
        with self.assertRaises(ZBApiException) as caught:
            ZeroBounce("doubled-key").get_activity("a@b.com")
        self.assertEqual(str(caught.exception), "Error: Invalid API key")

    def test_redirects_are_not_followed(self):
        with self.assertRaises(ZBApiException) as caught:
            ZeroBounce("redirect-key").get_credits()
        self.assertIn("redirect", str(caught.exception).lower())
        hosts = {item.host for item in self.transport.requests}
        self.assertEqual(hosts, {"api.zerobounce.net"})
        self.assertNotIn("evil.example", self.transport.requests[0].url)

    def test_parallel_clients_do_not_share_keys(self):
        def one(index):
            key = f"user-{index}-secret"
            client = ZeroBounce(key)
            credits = client.get_credits()
            validated = client.validate("ada@example.com")
            return key, credits.credits, getattr(validated, "echo_key", None)

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(one, range(12)))

        self.assertEqual(len(self.transport.requests), 24)
        seen = {}
        for recorded in self.transport.requests:
            seen.setdefault(recorded.api_key, 0)
            seen[recorded.api_key] += 1
            blob = recorded.url + recorded.body.decode(errors="replace")
            for other in seen:
                if other != recorded.api_key:
                    self.assertNotIn(other, blob)
        self.assertEqual(len(seen), 12)
        for key, credits, echo in results:
            self.assertEqual(credits, key)
            self.assertEqual(echo, key)
            for other, _, _ in results:
                if other != key:
                    self.assertNotIn(other, credits)
                    self.assertNotIn(other, echo or "")

