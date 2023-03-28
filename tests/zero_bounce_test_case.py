from . import BaseTestCase, MockResponse
from zerobouncesdk import (
    ZBApiException,
    ZBClientException,
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

    def test_response_contains_error(self):
        self.requests_mock.get.return_value = MockResponse({
            "error": "Invalid API key or your account ran out of credits",
        })

        with self.assertRaises(ZBApiException) as cm:
            self.zero_bounce_client.get_credits()
        expected_error = "Invalid API key or your account ran out of credits"
        self.assertEqual(str(cm.exception), expected_error)

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

    def test_blank_file_id(self):
        with self.assertRaises(ZBClientException) as cm:
            self.zero_bounce_client.get_file("  ", "any_download_path")
        expected_error = "Empty parameter: file_id"
        self.assertEqual(str(cm.exception), expected_error)
