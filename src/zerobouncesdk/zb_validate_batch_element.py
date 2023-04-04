from . import ZBClientException


class ZBValidateBatchElement:
    """This is the model for the POST /validatebatch request."""

    email_address: str = None

    ip_address: str = None

    def __init__(self, email_address: str, ip_address: str = None):
        if not email_address.strip():
            raise ZBClientException("Empty parameter: email_address")
        self.email_address = email_address
        self.ip_address = ip_address

    def to_json(self):
        json = {"email_address": str(self.email_address)}
        if self.ip_address is not None:
            json["ip_address"] = str(self.ip_address)
        return json
