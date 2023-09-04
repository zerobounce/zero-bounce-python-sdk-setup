from datetime import date, datetime
from pathlib import Path

from . import BaseTestCase, MockResponse
from zerobouncesdk import (
    ZBApiException,
    ZBClientException,
    ZBValidateStatus,
    ZBValidateSubStatus,
    ZBValidateBatchElement,
    ZBValidateBatchError,
    ZeroBounce,
)

class ZeroBounceTestCase(BaseTestCase):

    def test_init_blank_key(self):
        with self.assertRaises(ZBClientException) as cm:
            ZeroBounce("   ")
        expected_error = "Empty parameter: api_key"
        self.assertEqual(str(cm.exception), expected_error)

    def test_credits_invalid_key(self):
        self.requests_mock.get.return_value = MockResponse({
            "Credits": "-1",
        })

        response = self.zero_bounce_client.get_credits()
        self.assertEqual(response.credits, "-1")

    def test_credits_valid(self):
        self.requests_mock.get.return_value = MockResponse({
            "Credits": "12345",
        })

        response = self.zero_bounce_client.get_credits()
        self.assertEqual(response.credits, "12345")

    def test_response_contains_error(self):
        self.requests_mock.get.return_value = MockResponse({
            "error": "Invalid API key or your account ran out of credits",
        })

        with self.assertRaises(ZBApiException) as cm:
            self.zero_bounce_client.get_credits()
        expected_error = "Invalid API key or your account ran out of credits"
        self.assertEqual(str(cm.exception), expected_error)

    def test_api_usage_valid(self):
        self.requests_mock.get.return_value = MockResponse({
            "total": 9,
            "start_date": "3/1/2023",
            "end_date": "3/16/2023",
        })

        response = self.zero_bounce_client.get_api_usage(date(2023, 3, 1), date(2023, 3, 16))
        self.assertEqual(response.total, 9)
        self.assertEqual(response.start_date, date(2023, 3, 1))
        self.assertEqual(response.end_date, date(2023, 3, 16))

    def test_activity_valid(self):
        self.requests_mock.get.return_value = MockResponse({
            "found": True,
            "active_in_days": "180"
        })

        response = self.zero_bounce_client.get_activity("valid@example.com")
        self.assertTrue(response.found)
        self.assertEqual(response.active_in_days, "180")

    def test_validate_valid(self):
        self.requests_mock.get.return_value = MockResponse({
            "address": "invalid@example.com",
            "status": "invalid",
            "sub_status": "mailbox_not_found",
            "processed_at": "2023-03-28 12:30:18.990",
        })

        response = self.zero_bounce_client.validate("invalid@example.com", "99.110.204.1")
        self.assertEqual(response.address, "invalid@example.com")
        self.assertEqual(response.status, ZBValidateStatus.invalid)
        self.assertEqual(response.sub_status, ZBValidateSubStatus.mailbox_not_found)
        self.assertEqual(response.processed_at, datetime(2023, 3, 28, 12, 30, 18, 990000))

    def test_response_contains_errors(self):
        self.requests_mock.post.return_value = MockResponse({
            "email_batch": [],
            "errors": [{
                "email_address": "all",
                "error": "Invalid API Key or your account ran out of credits",
            }],
        })

        response = self.zero_bounce_client.validate_batch([ZBValidateBatchElement("any_email")])
        expected_error = "Invalid API Key or your account ran out of credits"
        self.assertEqual(len(response.email_batch), 0)
        self.assertEqual(len(response.errors), 1)
        self.assertIsInstance(response.errors[0], ZBValidateBatchError)
        self.assertEqual(response.errors[0].error, expected_error)

    def test_validate_batch_blank_email(self):
        with self.assertRaises(ZBClientException) as cm:
            ZBValidateBatchElement("  ")
        expected_error = "Empty parameter: email_address"
        self.assertEqual(str(cm.exception), expected_error)

    def test_validate_batch_no_emails(self):
        with self.assertRaises(ZBClientException) as cm:
            self.zero_bounce_client.validate_batch([])
        expected_error = "Empty parameter: email_batch"
        self.assertEqual(str(cm.exception), expected_error)

    def test_validate_batch_valid(self):
        self.requests_mock.post.return_value = MockResponse({
            "email_batch": [{
                "address": "valid@example.com",
                "status": "valid",
                "sub_status": "",
            },{
                "address": "invalid@example.com",
                "status": "invalid",
                "sub_status": "mailbox_not_found",
            }],
            "errors": []
        })

        response = self.zero_bounce_client.validate_batch([
            ZBValidateBatchElement("valid@example.com"),
            ZBValidateBatchElement("invalid@example.com"),
        ])
        self.assertEqual(len(response.email_batch), 2)
        self.assertEqual(response.email_batch[0].address, "valid@example.com")
        self.assertEqual(response.email_batch[0].status, ZBValidateStatus.valid)
        self.assertEqual(response.email_batch[0].sub_status, ZBValidateSubStatus.none)
        self.assertEqual(response.email_batch[1].address, "invalid@example.com")
        self.assertEqual(response.email_batch[1].status, ZBValidateStatus.invalid)
        self.assertEqual(response.email_batch[1].sub_status, ZBValidateSubStatus.mailbox_not_found)
        self.assertEqual(len(response.errors), 0)

    def test_response_contains_message_list(self):
        self.requests_mock.get.return_value = MockResponse({
            "success": "False",
            "message": ["api_key is invalid"],
        })

        response = self.zero_bounce_client.get_file("any_file_id", "any_download_path")
        expected_error = "api_key is invalid"
        self.assertFalse(response.success)
        self.assertEqual(response.message, expected_error)

    def test_response_contains_message(self):
        self.requests_mock.get.return_value = MockResponse({
            "success": False,
            "message": "File cannot be found.",
        })

        response = self.zero_bounce_client.get_file("invalid_file_id", "any_download_path")
        expected_error = "File cannot be found."
        self.assertFalse(response.success)
        self.assertEqual(response.message, expected_error)

    def test_invalid_file_path(self):
        with self.assertRaises(FileNotFoundError) as cm:
            self.zero_bounce_client.send_file("invalid_file_path", 1)
        expected_error = "[Errno 2] No such file or directory: 'invalid_file_path'"
        self.assertEqual(str(cm.exception), expected_error)

    @staticmethod
    def _delete_file(file: Path):
        try:
            file.unlink()
        except FileNotFoundError:
            pass

    def test_send_file_valid(self):
        self.requests_mock.post.return_value = MockResponse({
            "success": True,
            "message": "File Accepted",
            "file_name": "emails.txt",
            "file_id": "5e87c21f-45b2-4803-8daf-307f29fa7340",
        })
        file = Path("emails.txt")
        self.addCleanup(self._delete_file, file=file)
        file.touch()

        response = self.zero_bounce_client.send_file("emails.txt", 1)
        self.assertTrue(response.success)
        self.assertEqual(response.message, "File Accepted")
        self.assertEqual(response.file_name, "emails.txt")
        self.assertEqual(response.file_id, "5e87c21f-45b2-4803-8daf-307f29fa7340")

    def test_blank_file_id(self):
        with self.assertRaises(ZBClientException) as cm:
            self.zero_bounce_client.get_file("  ", "any_download_path")
        expected_error = "Empty parameter: file_id"
        self.assertEqual(str(cm.exception), expected_error)

    def test_file_status_valid(self):
        self.requests_mock.get.return_value = MockResponse({
            "success": True,
            "file_id": "5e87c21f-45b2-4803-8daf-307f29fa7340",
            "file_name": "emails.txt",
            "upload_date": "2023-03-28T12:30:18Z",
            "file_status": "Complete",
            "complete_percentage": "100%",
            "return_url": "Your return URL if provided when calling sendfile API",
        })

        response = self.zero_bounce_client.file_status("5e87c21f-45b2-4803-8daf-307f29fa7340")
        self.assertTrue(response.success)
        self.assertEqual(response.file_id, "5e87c21f-45b2-4803-8daf-307f29fa7340")
        self.assertEqual(response.file_name, "emails.txt")
        self.assertEqual(response.upload_date, datetime(2023, 3, 28, 12, 30, 18))
        self.assertEqual(response.file_status, "Complete")

    def test_get_file_valid(self):
        self.requests_mock.get.return_value = MockResponse(
            json_data=None,
            content=b""""Email Address","First Name","Last Name","Gender","ZB Status","ZB Sub Status","ZB Account","ZB Domain","ZB First Name","ZB Last Name","ZB Gender","ZB Free Email","ZB MX Found","ZB MX Record","ZB SMTP Provider","ZB Did You Mean"
"valid@example.com","","","","valid","","","","zero","bounce","male","False","true","mx.example.com","example",""
"spamtrap@example.com","","","","spamtrap","","","","zero","bounce","male","False","true","mx.example.com","example",""
"invalid@example.com","","","","invalid","mailbox_not_found","","","zero","bounce","male","False","true","mx.example.com","example",""
"catchall@example.com","","","","do_not_mail","global_suppression","catchall","example.com","","","","False","false","","",""
            """,
            headers={"Content-Type": "application/octet-stream"}
        )
        file = Path("results.txt")
        self.addCleanup(self._delete_file, file=file)

        self.assertFalse(file.is_file())
        response = self.zero_bounce_client.get_file("5e87c21f-45b2-4803-8daf-307f29fa7340", "results.txt")
        self.assertTrue(file.is_file())
        self.assertTrue(response.success)
        self.assertEqual(response.local_file_path, "results.txt")

    def test_delete_file_valid(self):
        self.requests_mock.get.return_value = MockResponse({
            "success": True,
            "message": "File Deleted",
            "file_name": "emails.txt",
            "file_id": "5e87c21f-45b2-4803-8daf-307f29fa7340",
        })

        response = self.zero_bounce_client.delete_file("5e87c21f-45b2-4803-8daf-307f29fa7340")
        self.assertTrue(response.success)
        self.assertEqual(response.message, "File Deleted")
        self.assertEqual(response.file_id, "5e87c21f-45b2-4803-8daf-307f29fa7340")
        self.assertEqual(response.file_name, "emails.txt")

    def test_find_email_status_invalid(self):
        self.requests_mock.get.return_value = mock_response = MockResponse({
            "email": "",
            "domain": "example.com",
            "format": "unknown",
            "status": "invalid",
            "sub_status": "no_dns_entries",
            "confidence": "undetermined",
            "did_you_mean": "",
            "failure_reason": "",
            "other_domain_formats": []
        })

        response = self.zero_bounce_client.find_email(
            "example.com", "John", "", "Doe"
        )
        for field, expected_value in mock_response.json().items():
            self.assertEqual(
                getattr(response, field), expected_value, f"invalid {field}"
            )

    def test_find_email_status_valid(self):
        self.requests_mock.get.return_value = mock_response = MockResponse({
            "email": "john.doe@example.com",
            "domain": "example.com",
            "format": "first.last",
            "status": "valid",
            "sub_status": "",
            "confidence": "high",
            "did_you_mean": "",
            "failure_reason": "",
            "other_domain_formats": [
                {
                    "format": "first_last",
                    "confidence": "high"
                },
                {
                    "format": "first",
                    "confidence": "medium"
                }
            ]
        })

        response = self.zero_bounce_client.find_email(
            "example.com", "John", "", "Doe"
        )
        for field, expected_value in mock_response.json().items():
            if field == "other_domain_formats":
                continue
            self.assertEqual(
                getattr(response, field), expected_value, f"invalid {field}"
            )
        self.assertEqual(len(response.other_domain_formats), 2)
        self.assertEqual(response.other_domain_formats[0].format, "first_last")
        self.assertEqual(response.other_domain_formats[0].confidence, "high")
        self.assertEqual(response.other_domain_formats[1].format, "first")
        self.assertEqual(response.other_domain_formats[1].confidence, "medium")
