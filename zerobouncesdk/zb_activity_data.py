from ._zb_response import ZBResponse


class ZBActivityDataResponse(ZBResponse):
    """This is the response for the GET /activity request."""

    found: bool = False

    active_in_days: str = None
