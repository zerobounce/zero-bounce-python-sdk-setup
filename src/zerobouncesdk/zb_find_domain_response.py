from typing import List

from . import ZBConfidence, ZBApiException
from ._zb_response import ZBResponse
from ._zb_utils import safe_enum_convert
from .zb_guess_format_response import ZBDomainFormat


class ZBFindDomainResponse(ZBResponse):
    """This is the response for the find_domain request."""

    domain: str = None
    """The domain that was used or found."""

    company_name: str = None
    """The company name that was used or found."""

    format: str = None
    """The guessed email format for the domain."""

    confidence: ZBConfidence = None
    """The confidence level for the guessed format."""

    did_you_mean: str = None
    """Suggestive fix for any input errors."""

    failure_reason: str = None
    """Reason for failure if the operation was unsuccessful."""

    other_domain_formats: List[ZBDomainFormat] = []
    """List of other possible domain formats with their confidence levels."""

    def __init__(self, data):
        super().__init__(data)
        if "Message" in data or "message" in data:
            message = data.get("message") or data.get("Message")
            raise ZBApiException(message)

        self.confidence = safe_enum_convert(ZBConfidence, self.confidence, "confidence", lowercase=True)

        self.other_domain_formats = [
            ZBDomainFormat(df_data) for df_data in data.get("other_domain_formats", [])
        ]

