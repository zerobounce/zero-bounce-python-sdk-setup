from typing import List

from . import ZBConfidence
from ._zb_response import ARRAY, STRING, ZBResponse, items_as_received
from ._zb_utils import safe_enum_convert
from .zb_guess_format_response import ZBDomainFormat


class ZBFindDomainResponse(ZBResponse):
    """This is the response for the find_domain request."""

    # A body made only of message keys is a rejected request, not a result.
    _MESSAGE_ONLY_IS_ERROR = True

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

    _FIELD_TYPES = {
        "domain": STRING, "company_name": STRING, "format": STRING, "confidence": STRING,
        "did_you_mean": STRING, "failure_reason": STRING, "other_domain_formats": ARRAY,
    }
    _ITEMS = {"other_domain_formats": ZBDomainFormat}

    def __init__(self, data):
        super().__init__(data)

        self.confidence = safe_enum_convert(ZBConfidence, self.confidence, "confidence", lowercase=True)

        self.other_domain_formats = items_as_received(data, "other_domain_formats", ZBDomainFormat)

