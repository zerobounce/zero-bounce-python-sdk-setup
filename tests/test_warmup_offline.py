"""Offline Warmup API suite: a fake transport answers like https://www.zerobounce.net/docs/warmup-api."""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError

from zerobouncesdk import ZBApiException, ZBClientException, ZeroBounceWarmup

KEY = "warmup-key-123"
CSV = "seed,provider\nseed1@example.org,gmail\n"


def _response(status, body=b"", content_type="application/json", headers=None):
    response = Response()
    response.status_code = status
    response._content = body if isinstance(body, bytes) else json.dumps(body).encode()
    response.headers["Content-Type"] = content_type
    response.encoding = "utf-8"
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


class Recorded:
    def __init__(self, request):
        parsed = urlparse(request.url)
        self.method = request.method
        self.url = request.url
        self.host = parsed.hostname
        self.path = parsed.path
        self.query = {k: v[-1] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        self.headers = {k.lower(): v for k, v in request.headers.items()}
        self.json = json.loads(request.body) if request.body else None


class WarmupTest(TestCase):
    def setUp(self):
        self.requests = []
        self.replies = {}

        def send(session, request, **kwargs):
            recorded = Recorded(request)
            self.requests.append(recorded)
            endpoint = (recorded.method, recorded.path[len("/api/v1/warmup"):])
            reply = self.replies.get(endpoint) or self.replies.get("*")
            if reply is not None:
                return reply(recorded) if callable(reply) else reply
            return self._documented(*endpoint)

        patcher = patch("requests.sessions.Session.send", send)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = ZeroBounceWarmup(KEY)

    @staticmethod
    def _documented(method, path):
        if (method, path) in (("DELETE", "/sending-accounts"), ("PUT", "/engagement-rule")):
            return _response(204, b"", "text/plain")
        if (method, path) == ("PUT", "/smtp-credentials"):
            return _response(200, b"", "text/plain")
        if path in ("/seeds/download", "/statistics/download"):
            return _response(200, CSV.encode(), "text/csv", {"Content-Disposition": "attachment; filename=warmup_seeds.csv"})
        if path == "/seed-count":
            return _response(200, 42)
        if path == "/engagement-rules":
            return _response(200, [{"id": -1, "name": "Custom"}, {"id": 0, "name": "Default"}])
        if (method, path) == ("DELETE", "/custom-engagement"):
            return _response(200, {"status": "ok", "deleted": True})
        if path == "/test-smtp-configuration":
            return _response(200, {"message": "Test email sent."})
        return _response(200, {"ok": True})

    def _only(self):
        self.assertEqual(len(self.requests), 1)
        return self.requests[0]

    def test_every_endpoint_method_and_path(self):
        out = Path(tempfile.mkdtemp())
        cases = [
            (lambda c: c.list_sending_accounts(), "GET", "/sending-accounts"),
            (lambda c: c.get_sending_account("sender@example.com"), "GET", "/sending-account"),
            (lambda c: c.add_sending_account("sender@example.com", "self_managed", engagement_rule_id=0), "POST", "/sending-accounts"),
            (lambda c: c.update_sending_account("sender@example.com", 1, 1, False), "PUT", "/sending-accounts"),
            (lambda c: c.delete_sending_account("sender@example.com"), "DELETE", "/sending-accounts"),
            (lambda c: c.change_from_address("old@example.com", "new@example.com"), "PUT", "/smtp-credentials"),
            (lambda c: c.list_from_addresses(), "GET", "/from-addresses"),
            (lambda c: c.get_engagement_rules(), "GET", "/engagement-rules"),
            (lambda c: c.set_engagement_rule("sender@example.com", 2), "PUT", "/engagement-rule"),
            (lambda c: c.get_custom_engagement("sender@example.com"), "GET", "/custom-engagement/sender%40example.com"),
            (lambda c: c.create_custom_engagement("sender@example.com", 20, 25, 25), "POST", "/custom-engagement"),
            (lambda c: c.update_custom_engagement("sender@example.com", 20, 25, 25), "PUT", "/custom-engagement"),
            (lambda c: c.delete_custom_engagement("sender@example.com", 1), "DELETE", "/custom-engagement"),
            (lambda c: c.get_seeds(), "GET", "/seeds"),
            (lambda c: c.download_seeds(), "GET", "/seeds/download"),
            (lambda c: c.get_seed_count(), "GET", "/seed-count"),
            (lambda c: c.get_progress_today(), "GET", "/progress-today"),
            (lambda c: c.get_sent_today(), "GET", "/sent-today"),
            (lambda c: c.get_emails_per_day(), "GET", "/emails-per-day"),
            (lambda c: c.get_statistics("sender@example.com"), "GET", "/statistics"),
            (lambda c: c.get_statistics_per_day("sender@example.com", "2026-09-01", "2026-09-14"), "GET", "/statistics-per-day"),
            (lambda c: c.get_statistics_detailed("sender@example.com"), "GET", "/statistics-detailed"),
            (lambda c: c.download_statistics("sender@example.com", str(out / "stats.csv")), "GET", "/statistics/download"),
            (lambda c: c.get_from_address_statistics("sender@example.com"), "GET", "/from-address-statistics"),
            (lambda c: c.check_domain_dmarc("sender@example.com"), "GET", "/check-domain-dmarc"),
            (lambda c: c.test_smtp_configuration("sender@example.com", "sender@example.com", "pw", "smtp.example.com", 587), "POST", "/test-smtp-configuration"),
        ]
        self.assertEqual(len(cases), 26)
        for call, method, path in cases:
            self.requests.clear()
            call(self.client)
            recorded = self._only()
            self.assertEqual((recorded.method, recorded.host), (method, "warmup-api.zerobounce.net"), path)
            self.assertEqual(recorded.path, "/api/v1/warmup" + path)
            self.assertEqual(recorded.headers["api-key"], KEY, path)
            self.assertNotIn("api_key", recorded.query, path)
            self.assertNotIn(KEY, recorded.url, path)
            if recorded.json is not None:
                self.assertEqual(recorded.headers["content-type"], "application/json", path)

    def test_documented_successes(self):
        self.assertIsNone(self.client.delete_sending_account("sender@example.com"))  # 204
        self.assertIsNone(self.client.set_engagement_rule("sender@example.com", 0))  # 204
        self.assertIsNone(self.client.change_from_address("old@example.com", "new@example.com"))  # empty 200
        self.assertEqual(self.client.get_seed_count(), 42)
        self.assertEqual(self.client.get_engagement_rules()[0]["name"], "Custom")
        self.assertEqual(self.client.delete_custom_engagement("sender@example.com", 4), {"status": "ok", "deleted": True})
        self.assertEqual(self.client.download_seeds(), CSV)
        saved = Path(tempfile.mkdtemp()) / "nested" / "warmup_seeds.csv"
        self.client.download_seeds(str(saved))
        self.assertEqual(saved.read_text(), CSV)

    def test_request_bodies_and_queries(self):
        self.client.add_sending_account("sender@example.com", "self_managed", engagement_rule_id=0, ignore_conflict=False)
        self.assertEqual(
            self._only().json,
            {"from_address": "sender@example.com", "onboarding_model": "self_managed", "engagement_rule_id": 0, "ignore_conflict": False},
        )

        self.requests.clear()
        self.client.add_sending_account(
            "sender@example.com",
            "zb_managed",
            email_content={"company_name": "Acme", "types_of_emails": ["marketing"]},
            managed_sending={"weekdays_only": True, "timezone": "Europe/Bucharest", "timezone_offset": 3.0,
                             "warmup_start_date": date(2026, 9, 15)},
        )
        body = self._only().json
        self.assertNotIn("engagement_rule_id", body)
        self.assertEqual(body["email_content"]["types_of_emails"], ["marketing"])
        self.assertEqual(body["managed_sending"]["warmup_start_date"], "2026-09-15")

        self.requests.clear()
        self.client.update_sending_account("sender@example.com", 1, 4, True)
        self.assertEqual(
            self._only().json,
            {"team_id": 1, "from_address": "sender@example.com", "engagement_rule_id": 1, "status_id": 4, "auto_enable": True},
        )

        self.requests.clear()
        self.client.change_from_address("old@example.com", "new@example.com")
        self.assertEqual(self._only().json, {"team_id": 1, "old_from_address": "old@example.com", "new_from_address": "new@example.com"})

        self.requests.clear()
        self.client.set_engagement_rule("sender@example.com", 2)
        recorded = self._only()
        self.assertEqual((recorded.query, recorded.json), ({"c_from": "sender@example.com"}, {"rule_id": 2}))

        self.requests.clear()
        self.client.delete_custom_engagement("sender@example.com", 1)
        recorded = self._only()
        self.assertEqual(recorded.query, {})  # the docs: query parameters here return 422
        self.assertEqual(recorded.json, {"c_from": "sender@example.com", "engagement_rule_id": 1})

        self.requests.clear()
        self.client.list_from_addresses(search_from="acme", offset=0, limit=10)
        self.assertEqual(self._only().query, {"search_from": "acme", "offset": "0", "limit": "10"})

        self.requests.clear()
        self.client.get_statistics_per_day("sender@example.com", date(2026, 9, 1), "2026-09-14")
        self.assertEqual(
            self._only().query,
            {"from_address": "sender@example.com", "start_date": "2026-09-01", "end_date": "2026-09-14"},
        )

        self.requests.clear()
        self.client.check_domain_dmarc("sender@example.com", dkim_selector="default")
        self.assertEqual(self._only().query, {"from_address": "sender@example.com", "dkim_selector": "default"})

        self.requests.clear()
        self.client.create_custom_engagement("sender@example.com", 20, 25, 25)
        self.assertEqual(self._only().json, {"c_from": "sender@example.com", "reply_pct": 20, "important_pct": 25, "click_pct": 25})

    def test_invalid_arguments_send_nothing(self):
        attempts = [
            lambda: ZeroBounceWarmup("  "),
            lambda: ZeroBounceWarmup(KEY, base_url="http://warmup-api.zerobounce.net"),
            lambda: self.client.get_sending_account(""),
            lambda: self.client.add_sending_account("sender@example.com", "managed"),
            lambda: self.client.add_sending_account("sender@example.com", "self_managed"),
            lambda: self.client.add_sending_account("sender@example.com", "self_managed", engagement_rule_id=5),
            lambda: self.client.add_sending_account("sender@example.com", "self_managed", engagement_rule_id=-1),
            lambda: self.client.add_sending_account("sender@example.com", "self_managed", engagement_rule_id=0, email_content={}),
            lambda: self.client.add_sending_account("s@example.com", "zb_managed", email_content={"types_of_emails": ["promo"]}),
            lambda: self.client.add_sending_account("s@example.com", "zb_managed", managed_sending={"timezone_offset": 15}),
            lambda: self.client.add_sending_account("s@example.com", "zb_managed", managed_sending={"warmup_start_date": "15/09/2026"}),
            lambda: self.client.update_sending_account("s@example.com", 1, 9, False),
            lambda: self.client.update_sending_account("s@example.com", 7, 1, False),
            lambda: self.client.update_sending_account("s@example.com", 1, 1, None),
            lambda: self.client.change_from_address("old@example.com", " "),
            lambda: self.client.list_from_addresses(search_from="acme corp"),
            lambda: self.client.list_from_addresses(search_from="50%"),
            lambda: self.client.list_from_addresses(limit=-1),
            lambda: self.client.set_engagement_rule("s@example.com", -1),
            lambda: self.client.create_custom_engagement("s@example.com", 4, 25, 25),
            lambda: self.client.create_custom_engagement("s@example.com", 20, 41, 25),
            lambda: self.client.create_custom_engagement("s@example.com", 20, 10, 18),  # 18 > 10 x 1.75
            lambda: self.client.update_custom_engagement("s@example.com", 20, 25, 71),
            lambda: self.client.delete_custom_engagement("s@example.com", 0),
            lambda: self.client.get_statistics_per_day("s@example.com", "2026-09-14", "2026-09-01"),
            lambda: self.client.get_statistics_per_day("s@example.com", "09/01/2026", "2026-09-14"),
            lambda: self.client.check_domain_dmarc(""),
            lambda: self.client.check_domain_dmarc("example.com"),  # the live API wants an email address
            lambda: self.client.test_smtp_configuration("s@example.com", "u", "pw", "smtp.example.com", 0),
            lambda: self.client.test_smtp_configuration("s@example.com", "u", "", "smtp.example.com", 587),
        ]
        for attempt in attempts:
            self.requests.clear()
            with self.assertRaises(ZBClientException):
                attempt()
            self.assertEqual(self.requests, [], attempt)
        self.client.create_custom_engagement("s@example.com", 20, 10, 17)  # 17 <= 17.5

    def test_documented_errors_raise_with_status(self):
        cases = [
            (401, {"error": "Missing API-Key"}, "Missing API-Key"),
            (400, {"error": "engagement_rule_id does not exist"}, "engagement_rule_id does not exist"),
            (404, {"detail": "Not Found"}, "Not Found"),
            (409, {"error": "Sending account already exists"}, "Sending account already exists"),
            (422, {"detail": [{"loc": ["body", "engagement_rule_id"], "msg": "value is not a valid integer"}]},
             "engagement_rule_id: value is not a valid integer"),
            (429, {"error": "Custom engagement can be updated in 604000 seconds"}, "Custom engagement can be updated in 604000 seconds"),
            (502, {"error": "Upstream unavailable"}, "Upstream unavailable"),
        ]
        for status, body, message in cases:
            self.replies["*"] = _response(status, body)
            with self.assertRaises(ZBApiException) as caught:
                self.client.update_custom_engagement("s@example.com", 20, 25, 25)
            self.assertEqual(str(caught.exception), message)
            self.assertEqual(caught.exception.status_code, status)

    def test_redirects_html_and_csv_errors(self):
        self.replies["*"] = _response(302, b"", "text/plain", {"Location": "https://evil.example/"})
        with self.assertRaises(ZBApiException) as caught:
            self.client.get_seeds()
        self.assertEqual(caught.exception.status_code, 302)
        self.assertEqual(len(self.requests), 1)  # not followed

        self.replies["*"] = _response(200, b"<html><title>Access denied</title></html>", "text/html")
        with self.assertRaises(ZBApiException):
            self.client.get_seeds()
        with self.assertRaises(ZBApiException):
            self.client.download_seeds()

        self.replies["*"] = _response(200, {"error": "c_from not found"})
        with self.assertRaises(ZBApiException):
            self.client.download_statistics("s@example.com")

    def test_secrets_never_reach_error_messages(self):
        self.replies["*"] = lambda r: _response(400, {"error": f"bad login for password {r.json['password']} key {KEY}"})
        with self.assertRaises(ZBApiException) as caught:
            self.client.test_smtp_configuration("s@example.com", "user@example.com", "hunter2-secret", "smtp.example.com", 587)
        self.assertNotIn("hunter2-secret", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))

        def refuse(session, request, **kwargs):
            raise RequestsConnectionError(f"failed {request.url} with headers {dict(request.headers)}")

        with patch("requests.sessions.Session.send", refuse):
            with self.assertRaises(RequestsConnectionError) as caught:
                self.client.get_statistics("s@example.com")
        self.assertNotIn(KEY, str(caught.exception))

    def test_custom_base_url_and_timeout(self):
        client = ZeroBounceWarmup(KEY, base_url="https://warmup.example.zerobounce.net/", timeout=timedelta(seconds=5))
        client.get_engagement_rules()
        recorded = self._only()
        self.assertEqual((recorded.host, recorded.path), ("warmup.example.zerobounce.net", "/api/v1/warmup/engagement-rules"))
