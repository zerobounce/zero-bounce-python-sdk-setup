from zerobouncesdk._zb_response import ZBResponse
import json


class ZBGetCreditsResponse(ZBResponse):
    credits: str = None

    def __init__(self, j):
        # super().__init__(j)
        _dict = json.loads(j)
        self.credits = _dict["Credits"]
