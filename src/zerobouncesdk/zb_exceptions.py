class ZBException(Exception):
    pass


class ZBApiException(ZBException):
    """The API returned an error. ``status_code`` is the HTTP status when the client knows it."""

    def __init__(self, *args, status_code=None):
        super().__init__(*args)
        self.status_code = status_code


class ZBClientException(ZBException):
    pass
