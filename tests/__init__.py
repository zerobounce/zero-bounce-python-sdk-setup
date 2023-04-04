from unittest import TestCase
from unittest.mock import patch

from zerobouncesdk import ZeroBounce

class BaseTestCase(TestCase):

    def setUp(self):
        requests_patch = patch("zerobouncesdk.zerobouncesdk.requests")
        self.addCleanup(requests_patch.stop)
        self.requests_mock = requests_patch.start()
        self.zero_bounce_client = ZeroBounce("dummy_key")


class MockResponse:
    def __init__(self, json_data, content=None, headers=None):
        self.json_data = json_data
        self.content = content
        self.headers = {"Content-Type": "application/json"}
        if headers is not None:
            self.headers = headers

    def json(self):
        return self.json_data
