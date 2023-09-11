from typing import List

from zerobouncesdk.zb_confidence import ZBConfidence
from zerobouncesdk.zb_exceptions import ZBApiException
from zerobouncesdk.zb_validate_status import ZBValidateStatus
from zerobouncesdk.zb_validate_sub_status import ZBValidateSubStatus

from ._zb_response import ZBResponse


class ZBDomainFormat(ZBResponse):
    """This represents how a domain may format its emails
    (and how likely it is to do so a certain way)
    """

    format: str = None

    confidence: ZBConfidence = None

    def __init__(self, data=None):
        super().__init__(data)
        self.confidence = ZBConfidence(self.confidence.lower())


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

        self.status = ZBValidateStatus(self.status.lower())
        self.sub_status = ZBValidateSubStatus(self.sub_status.lower())
        self.confidence = ZBConfidence(self.confidence.lower())

        self.other_domain_formats = [
            ZBDomainFormat(df_data) for df_data in data["other_domain_formats"]
        ]
