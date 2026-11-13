from typing import Union

from ._zb_response import _INTEGER_STRING, ZBFieldTypeError, ZBResponse


class ZBGetCreditsResponse(ZBResponse):
    """This is the response for the GET /credits request."""

    credits: Union[str, int] = None
    """The credit balance as the API sends it: a string holding an integer ("-1" for a dead key), as the live API
    sends it, or a JSON integer (zerobounce.net's example is ``{"Credits": 2375323}``)."""

    # An integer, sent as a JSON string or a JSON number; "abc", "5.0", 5.5 or true is the wrong shape.
    _FIELD_TYPES = {"Credits": (str, int)}
    _REQUIRED = ("Credits",)
    _SDK_FIELDS = ("credits",)

    @classmethod
    def _check_values(cls, data):
        credits = data["Credits"]
        if isinstance(credits, str) and not _INTEGER_STRING.fullmatch(credits):
            raise ZBFieldTypeError("Credits is not an integer")

    def __init__(self, data):
        self.credits = data.get("Credits")
