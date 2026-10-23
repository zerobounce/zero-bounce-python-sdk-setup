from . import ZBApiException, ZBConfidence
from ._zb_response import ZBResponse
from ._zb_utils import safe_enum_convert


class ZBFindEmailFormatResponse(ZBResponse):
    """This is the response for the find_email_format request."""

    email: str = None
    """The guessed email address."""

    email_confidence: ZBConfidence = None
    """The confidence level for the guessed email address."""

    domain: str = None
    """The domain that was used or found."""

    company_name: str = None
    """The company name that was used or found."""

    did_you_mean: str = None
    """Suggestive fix for any input errors."""

    failure_reason: str = None
    """Reason for failure if the operation was unsuccessful."""

    def __init__(self, data):
        super().__init__(data)
        if "Message" in data or "message" in data:
            message = data.get("message", data.get("Message"))
            raise ZBApiException(message)
        self.email_confidence = safe_enum_convert(
            ZBConfidence, self.email_confidence, "email_confidence", lowercase=True
        )

