"""
Integration tests for ZeroBounce SDK.
These tests make real API calls and require a valid API key.

To run these tests, set the ZEROBOUNCE_API_KEY environment variable:
    export ZEROBOUNCE_API_KEY="your-api-key-here"
    python -m unittest tests.zero_bounce_integration_test
"""
import os
import unittest
from unittest import skipIf

from zerobouncesdk import (
    ZBApiException,
    ZBClientException,
    ZBConfidence,
    ZBApiUrl,
    ZeroBounce,
)


def has_api_key():
    """Check if API key is available in environment."""
    return bool(os.environ.get('ZEROBOUNCE_API_KEY', '').strip())


SKIP_IF_NO_API_KEY = skipIf(not has_api_key(), "ZEROBOUNCE_API_KEY environment variable not set")


class ZeroBounceIntegrationTestCase(unittest.TestCase):
    """Integration tests that make real API calls to ZeroBounce service."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures once for all tests."""
        api_key = os.environ.get('ZEROBOUNCE_API_KEY', '').strip()
        if not api_key:
            # Skip all tests if no API key, but setUpClass still runs
            return
        
        cls.api_key = api_key
        cls.client_default = ZeroBounce(api_key)
        cls.client_usa = ZeroBounce(api_key, base_url=ZBApiUrl.API_USA_URL)
        cls.client_eu = ZeroBounce(api_key, base_url=ZBApiUrl.API_EU_URL)

    def setUp(self):
        """Set up test fixtures before each test method."""
        if not has_api_key():
            self.skipTest("ZEROBOUNCE_API_KEY environment variable not set")
        
        # Use the default client for most tests
        self.client = self.client_default

    @SKIP_IF_NO_API_KEY
    def test_get_credits(self):
        """Test getting credits from the API."""
        response = self.client.get_credits()
        # Credits should be a string or number
        self.assertIsNotNone(response.credits)

    @SKIP_IF_NO_API_KEY
    def test_init_with_custom_base_url_string(self):
        """Test initializing with a custom base URL string."""
        custom_url = "https://api.zerobounce.net/v2"
        client = ZeroBounce(self.api_key, base_url=custom_url)
        response = client.get_credits()
        self.assertIsNotNone(response.credits)

    @SKIP_IF_NO_API_KEY
    def test_init_with_enum_base_url(self):
        """Test initializing with enum base URL."""
        client = ZeroBounce(self.api_key, base_url=ZBApiUrl.API_DEFAULT_URL)
        response = client.get_credits()
        self.assertIsNotNone(response.credits)

    @SKIP_IF_NO_API_KEY
    def test_validate_email(self):
        """Test validating an email address."""
        # Use a known invalid email for testing
        response = self.client.validate("invalid@example.com")
        self.assertIsNotNone(response.status)
        self.assertIsNotNone(response.address)

    @SKIP_IF_NO_API_KEY
    def test_find_email_format_with_domain(self):
        """Test find_email_format with domain parameter."""
        response = self.client.find_email_format(
            first_name="John",
            domain="example.com",
            last_name="Doe"
        )
        self.assertIsNotNone(response.email)
        self.assertIsInstance(response.email_confidence, (ZBConfidence, type(None)))

    @SKIP_IF_NO_API_KEY
    def test_find_domain_with_domain(self):
        """Test find_domain with domain parameter."""
        response = self.client.find_domain(domain="example.com")
        self.assertIsNotNone(response.domain)
        self.assertIsInstance(response.confidence, (ZBConfidence, type(None)))

    @SKIP_IF_NO_API_KEY
    def test_api_regions(self):
        """Test that different API regions work."""
        # Test default region
        response_default = self.client_default.get_credits()
        self.assertIsNotNone(response_default.credits)

        # Test USA region (if it exists and works)
        try:
            response_usa = self.client_usa.get_credits()
            self.assertIsNotNone(response_usa.credits)
        except Exception:
            # Some regions might not be available for all accounts
            pass

        # Test EU region (if it exists and works)
        try:
            response_eu = self.client_eu.get_credits()
            self.assertIsNotNone(response_eu.credits)
        except Exception:
            # Some regions might not be available for all accounts
            pass

    @SKIP_IF_NO_API_KEY
    def test_error_handling_invalid_key(self):
        """Test error handling with invalid API key."""
        invalid_client = ZeroBounce("invalid_key_12345")
        with self.assertRaises(ZBApiException):
            invalid_client.get_credits()

    def test_init_blank_key(self):
        """Test that blank API key raises exception."""
        with self.assertRaises(ZBClientException) as cm:
            ZeroBounce("   ")
        expected_error = "Empty parameter: api_key"
        self.assertEqual(str(cm.exception), expected_error)

    def test_init_invalid_base_url_type(self):
        """Test that invalid base_url type raises exception."""
        with self.assertRaises(ZBClientException) as cm:
            ZeroBounce("test_key", base_url=12345)
        self.assertIn("Invalid base_url type", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

