from typing import List

from . import (
    ZBConfidence,
    ZBValidateStatus,
    ZBValidateSubStatus,
)
from ._zb_response import ARRAY, STRING, ZBResponse
from ._zb_utils import safe_enum_convert


class ZBDomainFormat(ZBResponse):
    """This represents how a domain may format its emails
    (and how likely it is to do so a certain way)
    """

    format: str = None

    confidence: ZBConfidence = None

    _FIELD_TYPES = {"format": STRING, "confidence": STRING}

    def __init__(self, data=None):
        super().__init__(data)
        self.confidence = safe_enum_convert(ZBConfidence, self.confidence, "confidence", lowercase=True)


class ZBGuessFormatResponse(ZBResponse):
    """This is the response for the GET /guessformat request."""

    # A body made only of message keys is a rejected request, not a result.
    _MESSAGE_ONLY_IS_ERROR = True

    email: str = None

    domain: str = None

    format: str = None

    status: ZBValidateStatus = None

    sub_status: ZBValidateSubStatus = None

    confidence: ZBConfidence = None

    failure_reason: str = None

    did_you_mean: str = None

    other_domain_formats: List[ZBDomainFormat] = []

    _FIELD_TYPES = {
        "email": STRING, "domain": STRING, "format": STRING, "status": STRING, "sub_status": STRING,
        "confidence": STRING, "failure_reason": STRING, "did_you_mean": STRING, "other_domain_formats": ARRAY,
    }
    _ITEMS = {"other_domain_formats": ZBDomainFormat}

    def __init__(self, data):
        super().__init__(data)

        self.status = safe_enum_convert(ZBValidateStatus, self.status, "status", lowercase=True)
        self.sub_status = safe_enum_convert(ZBValidateSubStatus, self.sub_status, "sub_status", lowercase=True)
        self.confidence = safe_enum_convert(ZBConfidence, self.confidence, "confidence", lowercase=True)

        self.other_domain_formats = [
            ZBDomainFormat(df_data) for df_data in (data.get("other_domain_formats") or [])
        ]
