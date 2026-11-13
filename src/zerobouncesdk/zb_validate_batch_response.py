from typing import List

from ._zb_response import ARRAY, STRING, ZBResponse
from .zb_validate_response import ZBValidateResponse


class ZBValidateBatchEmail(ZBValidateResponse):
    pass


class ZBValidateBatchError(ZBResponse):
    error: str = None

    email_address: str = None

    _FIELD_TYPES = {"error": STRING, "email_address": STRING}


class ZBValidateBatchResponse(ZBResponse):
    """This is the response for the POST /validatebatch request."""

    email_batch: List[ZBValidateBatchEmail] = None
    """An Array of validated emails"""

    errors: List[ZBValidateBatchError] = None
    """An Array of errors encountered, if any"""

    _FIELD_TYPES = {"email_batch": ARRAY, "errors": ARRAY}
    _ITEMS = {"email_batch": ZBValidateBatchEmail, "errors": ZBValidateBatchError}

    def __init__(self, data):
        self.email_batch = [ZBValidateBatchEmail(email) for email in (data.get("email_batch") or [])]
        self.errors = [ZBValidateBatchError(error) for error in (data.get("errors") or [])]
