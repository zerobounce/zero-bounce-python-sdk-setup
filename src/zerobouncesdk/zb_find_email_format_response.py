from . import ZBConfidence
from ._zb_response import ZBResponse


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
        if self.email_confidence and isinstance(self.email_confidence, str):
            self.email_confidence = ZBConfidence(self.email_confidence.lower())

