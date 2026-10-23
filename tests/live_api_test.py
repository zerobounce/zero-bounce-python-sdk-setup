"""Opt-in live API suite: calls every SDK method against the real API to check payloads and response shapes.

Not collected by ``pytest`` and not run by CI. Run it explicitly:

    export ZEROBOUNCE_API_KEY=...            # validation API tests (skipped without it)
    export ZEROBOUNCE_WARMUP_API_KEY=...     # Warmup API tests (skipped without it)
    python -m unittest tests.live_api_test -v

By default only free calls run: sandbox addresses (no credits), reads, and requests that are expected to
fail (unknown file IDs, S3 / SFTP without an integration) to check the API accepts the payload. The free
tests check that the credit balance did not change. Two flags opt in to more:

    ZEROBOUNCE_LIVE_SPEND=1     spends credits: scoring, activity, email finder, and full bulk round trips
                                (upload, wait, download, delete) for validation, scoring, email finder,
                                domain search and the list evaluator
    ZEROBOUNCE_LIVE_CHANGES=1   reversible account changes, each undone in cleanup even when a test fails:
                                a test allowlist filter, and a self-managed Warmup sending account

Never called, because they cannot be undone through the API: creating an Inbox Placement test (it cannot be
deleted while running), setting the Inbox Placement webhook (it cannot be cleared), and ZB-managed Warmup
onboarding (it starts mailbox provisioning).
"""

import io
import os
import tempfile
import time
import unittest
import uuid
import warnings
from datetime import date, timedelta

from zerobouncesdk import (
    ZBApiException,
    ZBApiUrl,
    ZBClientException,
    ZBGetFileOptions,
    ZBValidateBatchElement,
    ZBValidateStatus,
    ZeroBounce,
    ZeroBounceWarmup,
)

API_KEY = os.environ.get("ZEROBOUNCE_API_KEY", "").strip()
WARMUP_KEY = os.environ.get("ZEROBOUNCE_WARMUP_API_KEY", "").strip()
SPEND = os.environ.get("ZEROBOUNCE_LIVE_SPEND") == "1"
CHANGES = os.environ.get("ZEROBOUNCE_LIVE_CHANGES") == "1"

# A well-formed ID that matches no file: a malformed one can be blocked by Cloudflare instead of answered.
UNKNOWN_ID = "0d1b7a4e-1111-2222-3333-444455556666"
CALLBACK = "https://example.com/zerobounce-sdk-live-test"
JOB_TIMEOUT_S = 300


def _wait(check, timeout=JOB_TIMEOUT_S, every=10):
    """Call ``check`` until it returns a truthy value; return it, or None after ``timeout`` seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(every)
    return None


@unittest.skipUnless(API_KEY, "ZEROBOUNCE_API_KEY not set")
class FreeLiveTest(unittest.TestCase):
    """Free calls only; the credit balance must not change."""

    @classmethod
    def setUpClass(cls):
        cls.zb = ZeroBounce(API_KEY)
        cls.credits_before = int(cls.zb.get_credits().credits)

    @classmethod
    def tearDownClass(cls):
        after = int(cls.zb.get_credits().credits)
        if after != cls.credits_before:
            raise AssertionError(f"free live tests spent credits: {cls.credits_before} -> {after}")

    def assertPayloadAccepted(self, call, *rejections):
        """The call may fail, but not because the API rejected the payload's fields."""
        try:
            call()
        except ZBApiException as error:
            message = str(error).lower()
            for text in ("field is required", "missing param", "not permitted", "invalid request format", *rejections):
                self.assertNotIn(text, message, f"payload rejected: {error}")

    # -- account ------------------------------------------------------------------------------

    def test_credits_and_usage_get_and_post(self):
        self.assertGreaterEqual(int(self.zb.get_credits(use_post=True).credits), 0)
        end = date.today()
        for use_post in (False, True):
            usage = self.zb.get_api_usage(end - timedelta(days=30), end, use_post=use_post)
            self.assertIsInstance(usage.total, int)
            self.assertEqual(usage.end_date, end)

    def test_regions(self):
        for region in (ZBApiUrl.API_USA_URL, ZBApiUrl.API_EU_URL):
            self.assertGreaterEqual(int(ZeroBounce(API_KEY, base_url=region).get_credits().credits), 0)

    def test_regional_base_url_warns_about_the_bulk_host(self):
        client = ZeroBounce(API_KEY, base_url=ZBApiUrl.API_EU_URL)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with self.assertRaises(ZBApiException):
                client.file_status(UNKNOWN_ID)
        self.assertEqual(sum("regional host" in str(w.message) for w in caught), 1)

    # -- validation (sandbox addresses are free) ----------------------------------------------

    def test_validate_every_option_get_and_post(self):
        for use_post in (False, True):
            result = self.zb.validate("valid@example.com", ip_address="203.0.113.7", timeout=30, activity_data=True,
                                      verify_plus=False, domain_info=True, use_post=use_post)
            self.assertEqual(result.status, ZBValidateStatus.valid)
            self.assertIsInstance(result.mx_found, bool)
            self.assertIsNotNone(result.domain_website_exists)
            self.assertIsNotNone(result.processed_at)

    def test_validate_greylist_options_are_accepted(self):
        for kwargs in ({"greylist_processing": True}, {"greylist_processing": True, "callback_url": CALLBACK}):
            result = self.zb.validate("unknown@example.com", **kwargs)
            self.assertTrue(result.status is not None or result.message, kwargs)

    def test_validate_batch_with_every_option(self):
        # timeout goes out as a string: the API rejects the batch when it is a JSON number.
        result = self.zb.validate_batch(
            [ZBValidateBatchElement("valid@example.com"), ZBValidateBatchElement("invalid@example.com", "203.0.113.7")],
            timeout=30, activity_data=True, verify_plus=False,
        )
        self.assertEqual([e.status for e in result.email_batch], [ZBValidateStatus.valid, ZBValidateStatus.invalid])

    def test_email_finder_and_domain_without_a_result_are_free(self):
        # Charged only when a format is found; example.com has none.
        for use_post in (False, True):
            found = self.zb.find_email_format(domain="example.com", use_post=use_post)
            self.assertEqual(found.domain, "example.com")
            self.zb.find_domain(domain="example.com", use_post=use_post)
        self.zb.guess_format("example.com", first_name="John")

    def test_filters_list_get_and_post(self):
        self.assertIsInstance(self.zb.list_filters(), list)
        self.assertIsInstance(self.zb.list_filters(use_post=True), list)

    # -- inbox placement tester (read-only) ---------------------------------------------------

    def test_inbox_placement_reads(self):
        providers = self.zb.get_inbox_placement_providers()
        self.assertTrue(providers["emailProviders"]["items"])
        self.assertTrue(self.zb.get_inbox_placement_test_types()["testTypes"])
        listing = self.zb.list_inbox_placement_tests(status="finished", created_after="2026-01-01", page=1, page_size=5)
        self.assertIn("results", listing)
        self.assertIn("webhookUrl", self.zb.get_inbox_placement_webhook())

    # -- payloads checked through expected failures -------------------------------------------

    def test_unknown_files_fail_with_a_short_api_error(self):
        out = os.path.join(tempfile.mkdtemp(), "never.csv")
        for call in (
            lambda: self.zb.file_status(UNKNOWN_ID),
            lambda: self.zb.scoring_file_status(UNKNOWN_ID),
            lambda: self.zb.email_finder_file_status(UNKNOWN_ID),
            lambda: self.zb.domain_search_file_status(UNKNOWN_ID),
            lambda: self.zb.get_file(UNKNOWN_ID, out, ZBGetFileOptions(download_type="combined", activity_data=True)),
            lambda: self.zb.get_file(UNKNOWN_ID, out, stream=True),
            lambda: self.zb.scoring_get_file(UNKNOWN_ID, out),
            lambda: self.zb.email_finder_get_file(UNKNOWN_ID, out),
            lambda: self.zb.domain_search_get_file(UNKNOWN_ID, out, stream=True),
            lambda: self.zb.delete_file(UNKNOWN_ID),
            lambda: self.zb.scoring_delete_file(UNKNOWN_ID),
            lambda: self.zb.email_finder_delete_file(UNKNOWN_ID),
            lambda: self.zb.domain_search_delete_file(UNKNOWN_ID),
            lambda: self.zb.get_list_evaluator_result(UNKNOWN_ID),
            lambda: self.zb.send_evaluated_file(UNKNOWN_ID),
        ):
            with self.assertRaises(ZBApiException) as caught:
                call()
            self.assertLess(len(str(caught.exception)), 300)
            self.assertNotIn("<html", str(caught.exception).lower())
            self.assertNotIn(API_KEY, str(caught.exception))
        self.assertFalse(os.path.exists(out))

    def test_s3_and_sftp_payloads_are_accepted(self):
        # Without an AWS / SFTP integration these fail on the missing setup, after the payload is accepted.
        for call in (
            lambda: self.zb.list_s3files(bucket="zerobounce-sdk-live-test", search="x"),
            lambda: self.zb.validate_s3file("lists/live.csv", True, remove_duplicates=True, return_url=CALLBACK),
            lambda: self.zb.score_s3file("lists/live.csv", False, return_url=CALLBACK),
            lambda: self.zb.email_finder_s3file("lists/live.csv", True, return_url=CALLBACK),
            lambda: self.zb.domain_search_s3file("lists/live.csv", True, return_url=CALLBACK),
            lambda: self.zb.export_s3file(UNKNOWN_ID, export_bucket="zerobounce-sdk-live-test"),
            lambda: self.zb.validate_sftpfile("live.txt", True, remove_duplicates=False, return_url=CALLBACK),
            lambda: self.zb.score_sftpfile("live.txt", True, return_url=CALLBACK),
            lambda: self.zb.email_finder_sftpfile("live.txt", True, return_url=CALLBACK),
            lambda: self.zb.domain_search_sftpfile("live.txt", True, return_url=CALLBACK),
            lambda: self.zb.export_sftpfile(UNKNOWN_ID, export_path="/exports"),
        ):
            self.assertPayloadAccepted(call)


@unittest.skipUnless(API_KEY and SPEND, "set ZEROBOUNCE_API_KEY and ZEROBOUNCE_LIVE_SPEND=1 to spend credits")
class SpendingLiveTest(unittest.TestCase):
    """Credit-spending calls and full bulk round trips. Every job is deleted afterwards."""

    EMAILS = "email\nvalid@example.com\ninvalid@example.com\ncatch_all@example.com\n"

    @classmethod
    def setUpClass(cls):
        cls.zb = ZeroBounce(API_KEY)
        cls.folder = tempfile.mkdtemp()

    def _complete(self, status_call, file_id):
        def finished():
            try:
                status = status_call(file_id)
            except ZBApiException as error:
                # A job created by send_evaluated_file is "not found" for a short while after it is accepted.
                if "cannot be found" in str(error).lower():
                    return None
                raise
            return status if str(status.file_status).lower() == "complete" else None

        self.assertIsNotNone(_wait(finished), f"{file_id} did not complete within {JOB_TIMEOUT_S}s")

    def _round_trip(self, send, status, get, delete):
        sent = send()
        self.assertTrue(sent.success, sent)
        self.addCleanup(lambda: self._delete_quietly(delete, sent.file_id))
        self._complete(status, sent.file_id)
        for stream in (False, True):
            path = os.path.join(self.folder, f"{sent.file_id}-{stream}.csv")
            get(sent.file_id, path, stream)
            self.assertGreater(os.path.getsize(path), 0)

    @staticmethod
    def _delete_quietly(delete, file_id):
        try:
            delete(file_id)
        except ZBApiException:
            pass

    def test_single_calls(self):
        self.assertIsInstance(self.zb.score_email("support@zerobounce.net").score, int)
        self.assertIsInstance(self.zb.score_email("support@zerobounce.net", use_post=True).score, int)
        self.assertIsInstance(self.zb.get_activity("support@zerobounce.net").found, bool)
        self.assertIsInstance(self.zb.get_activity("support@zerobounce.net", use_post=True).found, bool)
        domain = self.zb.find_domain(domain="zerobounce.net")
        self.assertEqual(domain.domain, "zerobounce.net")
        self.assertTrue(domain.format)
        self.assertEqual(self.zb.find_domain(company_name="ZeroBounce").domain, "zerobounce.net")
        found = self.zb.find_email_format("John", domain="zerobounce.net", last_name="Doe")
        self.assertEqual(found.domain, "zerobounce.net")

    def test_bulk_validation(self):
        self._round_trip(
            lambda: self.zb.send_file_stream(io.BytesIO(self.EMAILS.encode()), "live.csv", 1, has_header_row=True,
                                             remove_duplicate=True, allow_phase_2=False),
            self.zb.file_status, lambda i, p, s: self.zb.get_file(i, p, stream=s), self.zb.delete_file)

    def test_bulk_scoring(self):
        path = os.path.join(self.folder, "scoring.csv")
        with open(path, "w") as handle:
            handle.write(self.EMAILS)
        self._round_trip(
            lambda: self.zb.scoring_send_file(path, 1, has_header_row=True),
            self.zb.scoring_file_status, lambda i, p, s: self.zb.scoring_get_file(i, p, stream=s),
            self.zb.scoring_delete_file)

    def test_bulk_email_finder(self):
        self._round_trip(
            lambda: self.zb.send_email_finder_file_stream(
                io.BytesIO(b"first_name,last_name,domain\nJohn,Doe,zerobounce.net\n"), "finder.csv",
                domain_column=3, first_name_column=1, last_name_column=2, has_header_row=True),
            self.zb.email_finder_file_status, lambda i, p, s: self.zb.email_finder_get_file(i, p, stream=s),
            self.zb.email_finder_delete_file)

    def test_bulk_domain_search(self):
        self._round_trip(
            lambda: self.zb.send_domain_search_file_stream(io.BytesIO(b"domain\nzerobounce.net\n"), "domains.csv",
                                                           domain_column=1, has_header_row=True),
            self.zb.domain_search_file_status, lambda i, p, s: self.zb.domain_search_get_file(i, p, stream=s),
            self.zb.domain_search_delete_file)

    def test_list_evaluator_then_validate_the_evaluated_list(self):
        rows = "email\n" + "".join(f"sdk.live.{i}@example.com\n" for i in range(110))
        evaluated = self.zb.send_list_evaluator_file_stream(io.BytesIO(rows.encode()), "evaluate.csv", 1)
        self.assertTrue(evaluated.file_id)
        result = _wait(lambda: (lambda r: r if r.status == "finished" else None)(
            self.zb.get_list_evaluator_result(evaluated.file_id)))
        self.assertIsNotNone(result, "list evaluation did not finish")
        self.assertEqual(result.progress, 100)
        job = self.zb.send_evaluated_file(evaluated.file_id)
        self.assertTrue(job.success)
        self.addCleanup(lambda: self._delete_quietly(self.zb.delete_file, job.file_id))
        self._complete(self.zb.file_status, job.file_id)


@unittest.skipUnless(API_KEY and CHANGES, "set ZEROBOUNCE_API_KEY and ZEROBOUNCE_LIVE_CHANGES=1 for account changes")
class FilterChangesLiveTest(unittest.TestCase):
    """Adds an allowlist filter for a reserved test domain and always removes it."""

    def test_filter_lifecycle(self):
        zb = ZeroBounce(API_KEY)
        domain = f"sdk-live-{uuid.uuid4().hex[:8]}.example.org"
        self.addCleanup(lambda: zb.delete_filter("allow", "domain", domain))
        self.assertIn("added", zb.add_filter("allow", "domain", domain)["Message"].lower())
        rule = {"rule": "allow", "target": "domain", "value": domain}
        # Filters take up to a minute to propagate.
        self.assertTrue(_wait(lambda: rule in zb.list_filters(), timeout=120), "filter never listed")
        self.assertIn(rule, zb.list_filters(use_post=True))


@unittest.skipUnless(WARMUP_KEY, "ZEROBOUNCE_WARMUP_API_KEY not set")
class WarmupLiveTest(unittest.TestCase):
    """Warmup API reads; with ZEROBOUNCE_LIVE_CHANGES=1 also a self-managed sending account's lifecycle."""

    @classmethod
    def setUpClass(cls):
        cls.warmup = ZeroBounceWarmup(WARMUP_KEY)

    def test_reads(self):
        w = self.warmup
        self.assertIn("accounts", w.list_sending_accounts())
        self.assertEqual({rule["id"] for rule in w.get_engagement_rules()}, {-1, 0, 1, 2, 3, 4})
        self.assertTrue(w.get_seeds())
        self.assertTrue(w.download_seeds().startswith("seed,provider"))
        self.assertIsInstance(w.get_seed_count(), int)
        self.assertIn("max_emails_today", w.get_progress_today())
        self.assertIn("sent_today", w.get_sent_today())
        self.assertIn("total_emails", w.get_emails_per_day())
        self.assertIn("results", w.list_from_addresses(search_from="example.com", offset=0, limit=5))
        dmarc = w.check_domain_dmarc("support@zerobounce.net", dkim_selector="google")
        self.assertIn("DMARC_status", dmarc)
        with self.assertRaises(ZBClientException):
            w.check_domain_dmarc("zerobounce.net")  # the API needs an email address
        with self.assertRaises(ZBApiException) as caught:
            w.get_sending_account(f"sdk-live-missing-{uuid.uuid4().hex[:8]}@example.com")
        self.assertEqual(caught.exception.status_code, 404)

    @unittest.skipUnless(CHANGES, "set ZEROBOUNCE_LIVE_CHANGES=1 for account changes")
    def test_self_managed_sending_account_lifecycle(self):
        w = self.warmup
        address = f"sdk-live-{uuid.uuid4().hex[:8]}@example.com"
        renamed = address.replace("sdk-live-", "sdk-live-renamed-")

        def remove(addr):
            try:
                w.delete_sending_account(addr)
            except ZBApiException:
                pass

        self.addCleanup(remove, address)
        self.addCleanup(remove, renamed)
        added = w.add_sending_account(address, "self_managed", engagement_rule_id=0, ignore_conflict=False)
        self.assertEqual(added["from_address"], address)
        self.assertIsNone(w.update_sending_account(address, 0, 4, False))  # 4 = Paused
        self.assertIsNone(w.change_from_address(address, renamed))
        self.assertIsNone(w.change_from_address(renamed, address))
        self.assertIsNone(w.set_engagement_rule(address, 1))
        custom = w.create_custom_engagement(address, reply_pct=20, important_pct=25, click_pct=25)
        self.assertFalse(custom["can_update"])
        self.assertIn("remaining_seconds", w.get_custom_engagement(address))
        with self.assertRaises(ZBApiException) as caught:
            w.update_custom_engagement(address, 21, 25, 25)
        self.assertEqual(caught.exception.status_code, 429)  # the 7 day cooldown
        self.assertEqual(w.delete_custom_engagement(address, 1), {"status": "ok", "deleted": True})
        self.assertIn("today_statistics", w.get_statistics(address))
        self.assertIn("statistics", w.get_statistics_per_day(address, date.today() - timedelta(days=7), date.today()))
        self.assertEqual(w.get_statistics_detailed(address)["c_from"], address)
        self.assertTrue(w.download_statistics(address))
        self.assertIsInstance(w.get_from_address_statistics(address), dict)
        self.assertIsNone(w.delete_sending_account(address))
        with self.assertRaises(ZBApiException):
            w.get_sending_account(address)


if __name__ == "__main__":
    unittest.main()
