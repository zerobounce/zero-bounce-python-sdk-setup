from ._zb_response import _INTEGER_STRING, STRING, ZBFieldTypeError, ZBResponse


class ZBGetCreditsResponse(ZBResponse):
    """This is the response for the GET /credits request."""

    credits: str = None
    """The credit balance as the API sends it: a string holding an integer ("-1" for a dead key)."""

    # Documented as a JSON string holding an integer; a bare number, "abc" or "5.0" is the wrong shape.
    _FIELD_TYPES = {"Credits": STRING}
    _REQUIRED = ("Credits",)
    _SDK_FIELDS = ("credits",)

    @classmethod
    def _check_values(cls, data):
        if not _INTEGER_STRING.fullmatch(data["Credits"]):
            raise ZBFieldTypeError("Credits is not an integer")

    def __init__(self, data):
        self.credits = data.get("Credits")
