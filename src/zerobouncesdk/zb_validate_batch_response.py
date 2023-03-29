from typing import List

from ._zb_response import ZBResponse
from .zb_validate_response import ZBValidateResponse


class ZBValidateBatchEmail(ZBValidateResponse):
    pass


class ZBValidateBatchError(ZBResponse):
    error: str = None

    email_address: str = None


class ZBValidateBatchResponse(ZBResponse):
    """This is the response for the POST /validatebatch request."""

    email_batch: List[ZBValidateBatchEmail] = None
    """An Array of validated emails"""

    errors: List[ZBValidateBatchError] = None
    """An Array of errors encountered, if any"""

    def __init__(self, data):
        self.email_batch = [ZBValidateBatchEmail(email) for email in data["email_batch"]]
        self.errors = [ZBValidateBatchError(error) for error in data["errors"]]
