from ._zb_response import ZBResponse


class ZBGetActivityResponse(ZBResponse):
    """This is the response for the GET /activity request."""

    found: bool = False

    active_in_days: str = None
    """30, 60, 90, 180, 365 or 365+; None when nothing was found."""

    active_first_seen: str = None
    """First date activity was seen (YYYY-MM-DD); None when nothing was found."""
