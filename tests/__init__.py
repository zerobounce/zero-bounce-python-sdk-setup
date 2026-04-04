import json
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
    def __init__(self, json_data=None, content=None, headers=None, status_code=200):
        self.status_code = status_code
        self.json_data = json_data
        if content is not None:
            self.content = content if isinstance(content, (bytes, bytearray)) else str(content).encode("utf-8")
        elif json_data is not None:
            self.content = json.dumps(json_data).encode("utf-8")
        else:
            self.content = b""
        self.headers = {"Content-Type": "application/json"}
        if headers is not None:
            self.headers = headers

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self.json_data
