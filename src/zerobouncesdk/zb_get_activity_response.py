from ._zb_response import ZBResponse
from ._zb_utils import parse_bool


class ZBGetActivityResponse(ZBResponse):
    """This is the response for the GET /activity request."""

    found: bool = False

    active_in_days: str = None
    """30, 60, 90, 180, 365 or 365+; None when nothing was found."""

    active_first_seen: str = None
    """First date activity was seen (YYYY-MM-DD); None when nothing was found."""

    def __init__(self, data=None):
        super().__init__(data)
        if "found" in self.__dict__:
            # "false" from the API would otherwise be a truthy string.
            self.found = parse_bool(self.__dict__["found"])
