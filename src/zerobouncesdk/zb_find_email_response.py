from typing import List

from ._zb_response import ZBResponse


class ZBDomainFormat(ZBResponse):
    """This represents how a domain may format its emails
    (and how likely it is to do so a certain way)
    """

    format: str = None

    confidence: str = None


class ZBFindEmailResponse(ZBResponse):
    """This is the response for the GET /guessformat request."""

    email: str = None

    domain: str = None

    format: str = None

    status: str = None

    sub_status: str = None

    confidence: str = None

    did_you_mean: str = None

    failure_reason: str = None

    other_domain_formats: List[ZBDomainFormat] = []

    def __init__(self, data):
        self.email = data["email"]
        self.domain = data["domain"]
        self.format = data["format"]
        self.status = data["status"]
        self.sub_status = data["sub_status"]
        self.confidence = data["confidence"]
        self.did_you_mean = data["did_you_mean"]
        self.failure_reason = data["failure_reason"]
        self.other_domain_formats = [
            ZBDomainFormat(df_data) for df_data in data["other_domain_formats"]
        ]
