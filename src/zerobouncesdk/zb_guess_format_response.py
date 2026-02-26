from typing import List

from . import (
    ZBConfidence,
    ZBApiException,
    ZBValidateStatus,
    ZBValidateSubStatus,
)
from ._zb_response import ZBResponse
from ._zb_utils import safe_enum_convert


class ZBDomainFormat(ZBResponse):
    """This represents how a domain may format its emails
    (and how likely it is to do so a certain way)
    """

    format: str = None

    confidence: ZBConfidence = None

    def __init__(self, data=None):
        super().__init__(data)
        self.confidence = safe_enum_convert(ZBConfidence, self.confidence, "confidence", lowercase=True)


class ZBGuessFormatResponse(ZBResponse):
    """This is the response for the GET /guessformat request."""

    email: str = None

    domain: str = None

    format: str = None

    status: ZBValidateStatus = None

    sub_status: ZBValidateSubStatus = None

    confidence: ZBConfidence = None

    failure_reason: str = None

    did_you_mean: str = None

    other_domain_formats: List[ZBDomainFormat] = []

    def __init__(self, data):
        super().__init__(data)
        if "Message" in data or "message" in data:
            message = data.get("message", data["Message"])
            raise ZBApiException(message)

        self.status = safe_enum_convert(ZBValidateStatus, self.status, "status", lowercase=True)
        self.sub_status = safe_enum_convert(ZBValidateSubStatus, self.sub_status, "sub_status", lowercase=True)
        self.confidence = safe_enum_convert(ZBConfidence, self.confidence, "confidence", lowercase=True)

        self.other_domain_formats = [
            ZBDomainFormat(df_data) for df_data in data.get("other_domain_formats", [])
        ]
