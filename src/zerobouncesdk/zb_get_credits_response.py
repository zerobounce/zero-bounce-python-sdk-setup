from ._zb_response import ZBResponse


class ZBGetCreditsResponse(ZBResponse):
    """This is the response for the GET /credits request."""

    credits: str = None

    def __init__(self, data):
        self.credits = data["Credits"]
